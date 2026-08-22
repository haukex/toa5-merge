"""
TOA5 Merge Tool
===============

Please see the README file for details.

Author, Copyright, and License
------------------------------

Copyright (c) 2025-2026 Hauke Dämpfling (haukex@zero-g.net)
at the Leibniz Institute of Freshwater Ecology and Inland Fisheries (IGB),
Berlin, Germany, https://www.igb-berlin.de/

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see https://www.gnu.org/licenses/
"""
import io
import re
import csv
import json
import os.path
import sqlite3
import logging
from decimal import Decimal
from textwrap import dedent
from io import TextIOWrapper
from contextlib import closing
from operator import itemgetter
from pathlib import PurePath, Path
from tempfile import TemporaryDirectory
from itertools import islice, groupby, chain
from typing import NamedTuple, Final, Literal
from collections.abc import Iterable, Sequence, Generator
from more_itertools import one, only, mark_ends
from igbpyutils.file import Filename, open_out
from igbpyutils.error import ex_repr
from unzipwalk import unzipwalk, FileType
from lsdelta import lsdelta
import toa5
from toa5_merge.utils import dual_csv_reader, find_superset

# spell-checker: ignore executemany

def _init_logging_notice():
    logging.addLevelName(25, 'NOTICE')
    return 25
NOTICE :Final[Literal[25]] = _init_logging_notice()

logger = logging.getLogger('toa5-merge')

class LoadOptions(NamedTuple):
    paths :Sequence[Filename]
    database :Filename
    station_name :str = ''
    table_name :str = ''
    program_sig :str = ''
    logger_serial :str = ''
    ignore_size :int = 0
    skip_seen :bool = False

class MergeOptions(NamedTuple):
    database :Filename
    max_lsdelta :int = 0
    drop_dupes :bool = False
    out_file :Filename = '-'

class Header(NamedTuple):
    hid :int
    raw :tuple[str,str,str,str]
    toa5 :toa5.FileHeader
    #: Is populated by :func:`_prepare_header_merge` and used by :func:`_check_dupe_rows` and :func:`_gen_csv_output`.
    col_map :list[int|None]

class Context(NamedTuple):
    opt :LoadOptions|MergeOptions
    con :sqlite3.Connection
    #: Holds parsed headers in parallel to the raw headers stored in SQLite. Is populated by :func:`_load_db` and/or :func:`_load_file`.
    hdr :dict[int, Header]

TS_COL = toa5.ColumnHeader(name='TIMESTAMP', unit='TS', prc='')
RN_COL = toa5.ColumnHeader(name='RECORD', unit='RN', prc='')

SCHEMA_VERSION :Final[int] = 2

def _load_db(con :sqlite3.Connection):
    con.execute('PRAGMA foreign_keys=ON')  # important for our design
    if one(con.execute('PRAGMA foreign_keys'))[0] != 1:  # double-check
        raise sqlite3.DatabaseError('failed to turn on foreign_keys')  # pragma: no cover
    if one(con.execute('PRAGMA user_version'))[0] != SCHEMA_VERSION:
        raise sqlite3.DatabaseError('database version does not match')
    hdr :dict[int, Header] = {}
    with closing(con.execute('SELECT id, header FROM headers ORDER BY id')) as sel_cur:
        for hid, raw_hdr in sel_cur:
            assert isinstance(hid, int) and isinstance(raw_hdr, str)
            rows = tuple(raw_hdr.splitlines())
            assert len(rows)==4 and len(rows)==toa5.HEADER_ROWS
            toa5_hdr = toa5.read_header(csv.reader(io.StringIO(raw_hdr), strict=True))
            hdr[hid] = Header(hid=hid, raw=rows, toa5=toa5_hdr, col_map=[])
    logger.debug('Existing database loaded')
    return hdr

def _init_db(con :sqlite3.Connection):
    """Initialize the SQLite3 database."""
    con.execute('PRAGMA synchronous=OFF')  # since it's temporary, disable sync for speed
    con.execute('PRAGMA foreign_keys=ON')  # important for our design
    if one(con.execute('PRAGMA foreign_keys'))[0] != 1:  # double-check
        raise sqlite3.DatabaseError('failed to turn on foreign_keys')  # pragma: no cover
    con.execute(f'PRAGMA user_version={SCHEMA_VERSION:d}')  # no placeholders supported?
    if one(con.execute('PRAGMA user_version'))[0] != SCHEMA_VERSION:
        raise sqlite3.DatabaseError('failed to set user_version')  # pragma: no cover
    # NOTE !!! REMEMBER to update SCHEMA_VERSION when changing schema
    con.execute(dedent('''\
    CREATE TABLE headers (
        id INTEGER PRIMARY KEY,      -- SQLite rowid
        header TEXT NOT NULL UNIQUE  -- raw, original header rows text (newlines normalized)
    )'''))
    con.execute(dedent('''\
    CREATE TABLE files (
        id INTEGER PRIMARY KEY,         -- SQLite rowid
        filename TEXT NOT NULL UNIQUE,  -- json
        size INTEGER,
        mtime INTEGER
    )'''))
    con.execute(dedent('''\
    CREATE TABLE row2file (
        rid INTEGER NOT NULL REFERENCES rows(id)  ON UPDATE CASCADE ON DELETE CASCADE,
        fid INTEGER NOT NULL REFERENCES files(id) ON UPDATE CASCADE ON DELETE CASCADE,
        UNIQUE (rid, fid)
    )'''))
    con.execute(dedent('''\
    CREATE TABLE rows (
        id INTEGER PRIMARY KEY,    -- SQLite rowid
        hid INTEGER NOT NULL REFERENCES headers(id) ON UPDATE CASCADE ON DELETE CASCADE,
        raw_row TEXT NOT NULL,     -- raw, original row text (newlines normalized)
        key TEXT NOT NULL,         -- just the first column in the row (timestamp)
        is_dupe BOOLEAN NOT NULL DEFAULT FALSE,  -- results of duplicate analysis (is actually INTEGER in SQLite)
        -- REMEMBER that two raw_rows may *look* the same, but actually be different if they have different headers.
        UNIQUE (hid, raw_row)
    )'''))
    logger.debug('Database initialized')

def _norm_nl(s :str) -> str:
    """Strips newline characters from the beginning and end of the string and normalizes any newlines within the string to LF.

    The reason I do this is because the database needs to be able to compare lines: for example, a raw input line "a,b,c" that
    occurs in the middle of a file will have a newline, while the exact same line at the end of a file may not end on a newline,
    but they still need to compare as equal. The same goes for two input files having different line ending formats. Also, I think
    doing this is okay for multiline CSV fields.
    """
    return s.replace('\r\n','\n').replace('\r','\n').strip('\n')

def _validate_row_fields(row :Sequence[str]):
    """Reject field contents that aren't supported in TOA5 data rows."""
    for field in row:
        if any(c in field for c in '"\r\n'):
            raise ValueError(f"unsupported characters in {field=}")

def _parse_raw_row(raw_row :str) -> list[str]:
    """Parse a normalized raw CSV row from the database."""
    row = one(csv.reader([raw_row], strict=True))
    _validate_row_fields(row)
    return row

class FileInfo(NamedTuple):
    """For use by :func:`_load_file`."""
    names :tuple[PurePath, ...]
    size :int|None
    mtime :int|None
    def json_fn(self):
        """A JSON string representation of the filename(s) for reporting to the user."""
        return json.dumps( self.names[0].as_posix() if len(self.names)==1 else [ name.as_posix() for name in self.names ], separators=(',', ':') )

def _load_file(ctx :Context, fi :FileInfo, handle :Iterable[str]) -> int:  # pylint: disable=too-many-locals
    """Parse a TOA5 file into the database and :attr:`Context.hdr`."""
    assert isinstance(ctx.opt, LoadOptions)
    csv_rd, raw_rd = dual_csv_reader(handle, strict=True)
    # ### Read the TOA5 Header
    try:
        toa5_hdr = toa5.read_header(csv_rd)
    except toa5.Toa5Error as ex:
        logger.log(logging.DEBUG if ctx.opt.ignore_size and fi.size and not fi.size % ctx.opt.ignore_size else logging.WARNING,
            'Skipping %s%s due to %s', fi.json_fn(), '' if fi.size is None else f" (size={fi.size})", ex_repr(ex))
        return 0
    # now get the raw header lines
    raw_hdr_lines = tuple(map(_norm_nl, islice(raw_rd, toa5.HEADER_ROWS)))
    assert len(raw_hdr_lines)==4 and len(raw_hdr_lines)==toa5.HEADER_ROWS
    # ### Check Filters
    if ( ctx.opt.station_name and ctx.opt.station_name != toa5_hdr.env_line.station_name or  # pylint: disable=too-many-boolean-expressions
         ctx.opt.table_name and ctx.opt.table_name != toa5_hdr.env_line.table_name or
         ctx.opt.program_sig and ctx.opt.program_sig != toa5_hdr.env_line.program_sig or
         ctx.opt.logger_serial and ctx.opt.logger_serial != toa5_hdr.env_line.logger_serial ):
        logger.debug('Skipping %s due to filter', fi.json_fn())
        return 0
    if toa5_hdr.columns[0] != TS_COL:
        raise NotImplementedError("Sorry, I don't handle non-TIMESTAMPed data (yet)")
    # ### Save Header
    # Assume that "ON CONFLICT DO UPDATE SET id=id RETURNING id" would be less efficient than a separate SELECT if there are a lot of
    # conflicts (which there will be), so use a hybrid solution that uses a second SELECT only if necessary. The trick here is that
    # "RETURNING id" doesn't return anything in the case of "ON CONFLICT DO NOTHING". Because there'll probably be a lot of conflicts
    # for the headers, this solution probably makes the most sense for the rows below.
    raw_hdr_join = '\n'.join(raw_hdr_lines)
    with ctx.con:
        hdr_ins = only(ctx.con.execute(
            'INSERT INTO headers (header) VALUES (?) ON CONFLICT (header) DO NOTHING RETURNING id', (raw_hdr_join,)))
        hid = ( one(ctx.con.execute('SELECT id FROM headers WHERE header=?', (raw_hdr_join,)))[0]
            if hdr_ins is None else hdr_ins[0] )
    assert isinstance(hid, int)
    header = Header(hid=hid, toa5=toa5_hdr, raw=raw_hdr_lines, col_map=[])
    if hid in ctx.hdr:
        if ctx.hdr[hid] != header:
            raise RuntimeError(f"Shouldn't happen: database gave same ID for different headers? a={ctx.hdr[hid]!r} b={header!r}")  # pragma: no cover
    else:
        ctx.hdr[hid] = header
    # ### Save File
    with ctx.con:
        # The file size is part of the "seen" check, and it's better to not mark files that have an error as "seen" (the
        # error could e.g. be a Ctrl-C during processing). So, we initially set the file size to 0, and update it below.
        fid = one(ctx.con.execute('''
            INSERT INTO files (filename,size,mtime) VALUES (?,?,?)
            ON CONFLICT (filename) DO UPDATE SET size=excluded.size, mtime=excluded.mtime
            RETURNING id  ''', (fi.json_fn(), 0, fi.mtime)))[0]
    assert isinstance(fid, int)
    # ### Save Rows
    ri :int = toa5.HEADER_ROWS+1  # init early for use in error handler below
    try:
        for _is_first, is_last, (ri, (row, raw_row)) in mark_ends(enumerate(zip(csv_rd, map(_norm_nl, raw_rd), strict=True), start=ri)):
            if len(row) != len(toa5_hdr.columns):
                logger.log(logging.DEBUG if is_last and ctx.opt.ignore_size and fi.size and not fi.size % ctx.opt.ignore_size else logging.WARNING,
                    'Skipping bad row %d in %s%s due to column count mismatch', ri, fi.json_fn(), '' if fi.size is None else f" (size={fi.size})")
                continue
            _validate_row_fields(row)
            # INSERT implicitly opens transaction:
            row_ins = only(ctx.con.execute(
                'INSERT INTO rows (hid, raw_row, key) VALUES (?,?,?) ON CONFLICT (hid,raw_row) DO NOTHING RETURNING id',
                (hid, raw_row, row[0]) ))
            rid = ( one(ctx.con.execute('SELECT id FROM rows WHERE hid=? AND raw_row=?', (hid, raw_row)))[0]
                if row_ins is None else row_ins[0] )  # see note about this pattern above
            assert isinstance(rid, int)
            ctx.con.execute('INSERT INTO row2file (rid, fid) VALUES (?,?) ON CONFLICT (rid,fid) DO NOTHING', (rid, fid))
            if not ri % 10000:  # batch commits for efficiency
                ctx.con.commit()
                logger.info('Loaded %d rows from %s so far...', ri-toa5.HEADER_ROWS, fi.json_fn())
        ctx.con.execute('UPDATE files SET size=? WHERE id=?', (fi.size, fid))
    except csv.Error as ex:
        logger.log(logging.DEBUG if ctx.opt.ignore_size and fi.size and not fi.size % ctx.opt.ignore_size else logging.WARNING,
            'Stopped parsing %s%s at row %d due to %s', fi.json_fn(), '' if fi.size is None else f" (size={fi.size})", ri, ex_repr(ex))
    finally:
        ctx.con.commit()
    return ri-int(toa5.HEADER_ROWS)  # not sure why the type checker needs the int() here

class DupeRow(NamedTuple):
    """For use in :func:`_check_dupe_rows`"""
    rid :int
    hdr :Header
    raw_row :str
    files :list[str]

class MergeError(RuntimeError):
    pass

def _maybe_dec(n :str):
    return format(Decimal(n), 'f') if 'e' in n or 'E' in n else n

def _check_dupe_rows(ctx :Context):  # pylint: disable=too-many-locals
    """Analyze the database for duplicate rows and mark them."""
    assert isinstance(ctx.opt, MergeOptions)
    logger.debug('Now analyzing duplicates...')
    select = '''
        SELECT r.key, r.hid, r.id, r.raw_row, f.filename  FROM rows AS r
        -- Note this only selects rows where there's more than one raw_row, which is why we additionally filter identical rows on output
        JOIN ( SELECT key FROM rows GROUP BY key HAVING COUNT(raw_row) > 1 ) AS d ON d.key = r.key
        JOIN row2file AS r2f ON r2f.rid = r.id
        JOIN    files AS f   ON r2f.fid = f.id
        ORDER BY r.key, r.hid, r.id, f.filename  '''
    seen_keys :set[str] = set()
    # NOTE the cursor needs to be closed explicitly if we abort iteration by throwing an exception
    with ctx.con, closing(ctx.con.execute(select)) as sel_cur:
        total_rows = ctx.con.execute('UPDATE rows SET is_dupe=FALSE').rowcount
        marked_rows = 0
        with_lsdelta = 0
        for ts_key,dup_key_rows in groupby(sel_cur, key=itemgetter(0)):
            assert isinstance(ts_key, str)
            if ts_key in seen_keys:  # this is only a double-check for me to catch potential errors in my SQL
                raise RuntimeError(f"Shouldn't happen: key {ts_key} seen more than once")  # pragma: no cover
            seen_keys.add(ts_key)
            rows :list[DupeRow] = []
            for (hid,rid,raw_row),rest in groupby(dup_key_rows, key=itemgetter(1,2,3)):
                assert isinstance(hid, int) and isinstance(rid, int) and isinstance(raw_row, str)
                rows.append(DupeRow(rid=rid, hdr=ctx.hdr[hid], raw_row=raw_row, files=[ f[4] for f in rest ]))
            assert len(rows)>1, rows
            r0 = rows[0]
            # Environment lines don't change a row's meaning when its raw data and column headers are identical
            if all( r.raw_row==r0.raw_row and r.hdr.toa5.columns==r0.hdr.toa5.columns for r in rows[1:] ):
                continue
            err_msg = ( f"Found a row with the same timestamp but different values (max_lsdelta={ctx.opt.max_lsdelta}):\n"
                f"key={ts_key!r} is shared by:\n" + '\n'.join( f"    row={r.raw_row!r} in files {r.files!r}" for r in rows ) )
            if not ctx.opt.max_lsdelta:
                raise MergeError(err_msg + '  max_lsdelta not set, so I expected them to be identical')
            # user specified max_lsdelta, so compare the rows using that
            assert r0.hdr.col_map, r0.hdr
            r0j = _parse_raw_row(r0.raw_row)
            r0c = [ '' if c is None else _maybe_dec(r0j[c]) for c in r0.hdr.col_map ]
            for r1 in rows[1:]:
                assert r1.hdr.col_map, r1.hdr
                r1j = _parse_raw_row(r1.raw_row)
                r1c = [ '' if c is None else _maybe_dec(r1j[c]) for c in r1.hdr.col_map ]
                had_lsdelta = False
                for ci,(r0v,r1v) in enumerate(zip(r0c, r1c, strict=True), start=1):
                    if r0v != r1v:
                        try:
                            d = abs(lsdelta(r0v, r1v))
                        except ValueError as ex:  # From lsdelta if r0 or r1 are not decimal numbers.
                            raise MergeError(  # pylint: disable=raise-missing-from
                                err_msg + f"\n  col={ci} first={r0v!r} second={r1v!r} exc={ex_repr(ex)}")
                        if d:
                            had_lsdelta = True
                        if d > ctx.opt.max_lsdelta:
                            raise MergeError(err_msg + f"\n  col={ci} first={r0v!r} second={r1v!r} delta={d}")
                if had_lsdelta:
                    with_lsdelta += 1
            # Since we haven't died by now, we must have determined that these rows are close enough.
            marked_rows += ctx.con.executemany('UPDATE rows SET is_dupe=TRUE WHERE id=?', ((r.rid,) for r in rows[1:])).rowcount
        logger.info('Marked %d of %d total rows as duplicates (%d with an lsdelta)', marked_rows, total_rows, with_lsdelta)

class HeaderMergeResult(NamedTuple):
    """For use by :func:`_prepare_header_merge`"""
    super_header :Header
    same_cols :bool

def _prepare_header_merge(ctx :Context) -> HeaderMergeResult:
    """Analyze the TOA5 headers and determine how to best merge them."""
    assert isinstance(ctx.opt, MergeOptions)
    # figure out which header includes all columns that appear in all other headers => the "super header"
    super_hdr_cols = find_superset([ frozenset(c.toa5.columns) for c in ctx.hdr.values() ])
    if super_hdr_cols is None:
        logger.warning('Here are the headers I have:\n\n%s', '\n\n'.join( '\n'.join(h.raw).strip() for h in ctx.hdr.values() ))
        raise MergeError('Unable to find a header that includes all columns across all inputs, so I don\'t know how to sort the columns.'
            ' You can create a file with a header with all columns in the desired order (and no rows) and include it in the input files.')
    # see which headers have columns the same as the super header
    super_hdr_ids = sorted( hi for hi,hv in ctx.hdr.items() if frozenset(hv.toa5.columns)==super_hdr_cols )
    assert super_hdr_ids, super_hdr_ids
    super_header = ctx.hdr[super_hdr_ids[-1]]  # pick the last one (this is an arbitrary choice)
    # provide some information to user
    if len(super_hdr_ids)>1:
        logger.info('Found more than one header that includes all %d columns, arbitrarily using the last one:\n%s',
            len(super_header.toa5.columns), '\n'.join( ctx.hdr[hid].raw[0].strip() for hid in super_hdr_ids ))
    else:
        logger.info('Found this one header that includes all %d columns:\n%s', len(super_header.toa5.columns), super_header.raw[0].strip())
    if env_lines := set( h.raw[0] for h in ctx.hdr.values() ) - { super_header.raw[0] }:
        logger.log(NOTICE, 'The following environment line(s) will be lost in the merge:\n%s',
            '\n'.join(ln.strip() for ln in sorted(env_lines)))
    # do all headers have the same columns? then we can output raw data without remapping columns
    # but generate the column maps anyway because _check_dupe_rows uses them too
    same_cols = len(super_hdr_ids)==len(ctx.hdr) and all( h.toa5.columns==super_header.toa5.columns for h in ctx.hdr.values() )
    # for each header, create a mapping that remaps the columns onto the super header
    for hdr in ctx.hdr.values():
        assert not hdr.col_map, hdr.col_map
        for col in super_header.toa5.columns:
            try:
                hdr.col_map.append( hdr.toa5.columns.index(col) )
            except ValueError:
                hdr.col_map.append( None )
        assert len(hdr.col_map) == len(super_header.toa5.columns), hdr.col_map
        logger.debug('Column map for hid %d: %s', hdr.hid, repr(hdr.col_map))
    return HeaderMergeResult(super_header=super_header, same_cols=same_cols)

def _gen_raw_output(ctx :Context) -> Generator[str]:
    """Generate the new merged TOA5 file data assuming all input files have identical columns."""
    assert isinstance(ctx.opt, MergeOptions)
    with closing(ctx.con.execute(f'''
            -- need a key in this query so it can be used in the ORDER BY
            SELECT MIN(key) AS key, raw_row FROM rows
                {'WHERE is_dupe=FALSE' if ctx.opt.drop_dupes else ''}
                GROUP BY raw_row ORDER BY key  ''')) as sel_cur:
        for _,raw_row in sel_cur:
            assert isinstance(raw_row, str)
            yield raw_row

NUMERIC_RE = re.compile(r'\A(?:[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?|INF)|NAN)\Z')
QUOTE_RE = re.compile(r'\A(?:[+-]?INF|NAN)\Z')

def _gen_csv_output(ctx :Context) -> Generator[str]:
    """Generate the new merged TOA5 file CSV data for output."""
    assert isinstance(ctx.opt, MergeOptions)
    # Although running the output through a temp table to remove duplicates is somewhat complicated,
    # it still seems like the safest way to deduplicate the remapped rows. The scan-then-write approach
    # is also good for guessing the data types of the columns (which may not always be 100% accurate,
    # for example, a string column containing only numbers will be detected as numeric here, but that
    # should be rare enough that we can ignore it), which influences quoting.
    is_numeric = [ True ] * one( { len(h.col_map) for h in ctx.hdr.values() } )
    opt :MergeOptions = ctx.opt  # just so it has a definite type in the following:
    def remapped_rows() -> Generator[tuple[str,str], None, None]:
        with closing(ctx.con.execute(f"SELECT key, hid, raw_row FROM rows {'WHERE is_dupe=FALSE' if opt.drop_dupes else ''}")) as sel_cur:
            for key,hid,raw_row in sel_cur:
                assert isinstance(key, str) and isinstance(hid, int) and isinstance(raw_row, str)
                row = _parse_raw_row(raw_row)
                r_row = [ None if c is None else row[c] for c in ctx.hdr[hid].col_map ]
                for i, field in enumerate(r_row):
                    if field is not None:
                        assert isinstance(field, str)
                        if NUMERIC_RE.fullmatch(field) is None:
                            is_numeric[i] = False
                yield json.dumps(r_row, separators=(',', ':')), key
    with ctx.con:
        ctx.con.execute('CREATE TEMP TABLE csv_output ( j_row TEXT NOT NULL UNIQUE, key TEXT NOT NULL )')
        ctx.con.executemany('INSERT INTO csv_output (j_row,key) VALUES (?,?) ON CONFLICT DO NOTHING', remapped_rows())
        with closing(ctx.con.execute('SELECT key, j_row FROM csv_output ORDER BY key')) as sel_cur:
            for _key,j_row in sel_cur:
                yield ','.join( '' if c is None else c if is_numeric[i] and QUOTE_RE.fullmatch(c) is None else f'"{c}"'
                                for i,c in enumerate(json.loads(j_row)) )
        ctx.con.execute('DROP TABLE csv_output')

def _load_files(ctx :Context):
    assert isinstance(ctx.opt, LoadOptions)
    logger.debug('Now loading all files from %d path(s)...', len(ctx.opt.paths))
    f_cnt = 0
    row_cnt = 0
    common_parent = Path(os.path.commonpath(ctx.opt.paths))
    def _matcher(names :Sequence[PurePath]) -> bool:
        if len(names)>1:  # only physical files, not in archives
            return True
        st = Path(names[0]).stat()
        json_fn = json.dumps(names[0].relative_to(common_parent).as_posix())  # same filename encoding as FileInfo.json_fn
        seen = only(ctx.con.execute('SELECT id FROM files WHERE filename=? AND size=? AND mtime=?',
            ( json_fn, st.st_size, int(st.st_mtime) ) ))
        if seen is None:
            return True
        logger.info('Skipping %s because already in DB', json_fn)
        return False
    for f_cnt, result in enumerate(unzipwalk(ctx.opt.paths, matcher=_matcher if ctx.opt.skip_seen else None), start=1):
        # To skip archives, they need to appear in the files table, so put them there
        if len(result.names)==1 and result.typ==FileType.ARCHIVE:
            st = Path(result.names[0]).stat()
            json_fn = json.dumps(result.names[0].relative_to(common_parent).as_posix())  # same filename encoding as FileInfo.json_fn
            with ctx.con:
                ctx.con.execute('''INSERT INTO files (filename,size,mtime) VALUES (?,?,?)
                    ON CONFLICT (filename) DO UPDATE SET size=excluded.size, mtime=excluded.mtime''',
                    ( json_fn, st.st_size, int(st.st_mtime) ) )
            continue
        if result.typ!=FileType.FILE or result.names[-1].suffix.lower()!='.dat':
            continue
        assert result.hnd, result
        mtime = int(Path(result.names[0]).stat().st_mtime) if len(result.names)==1 else None
        # make the filename a little more user-friendly by making it relative to the common parent of the input paths
        rel_names = (result.names[0].relative_to(common_parent),) + result.names[1:]
        with TextIOWrapper(result.hnd, encoding='ASCII', newline='') as handle:  # pyright: ignore [reportArgumentType]
            row_cnt += _load_file(ctx, FileInfo(names=rel_names, size=result.size, mtime=mtime), handle)
        if not f_cnt % 10000:  # pragma: no cover  # just informational for user, doesn't really need automated coverage
            logger.info('Loaded %d rows from %d files so far...', row_cnt, f_cnt)
    logger.info('Finished loading %d rows from %d files', row_cnt, f_cnt)

def _write_out(ctx :Context, hdr_merge :HeaderMergeResult):
    assert isinstance(ctx.opt, MergeOptions)
    with open_out(ctx.opt.out_file, mode='x', encoding='UTF-8', newline='') as ofh:
        for ln in chain(hdr_merge.super_header.raw, _gen_raw_output(ctx) if hdr_merge.same_cols else _gen_csv_output(ctx)):
            print(ln, file=ofh, end='\r\n')  # explicitly use CRLF since that's what TOA5 files use, and do it here so it applies to STDOUT too
    if ctx.opt.out_file and ctx.opt.out_file!='-':
        logger.log(NOTICE, 'Wrote output to %s (%s)', ctx.opt.out_file, 'raw' if hdr_merge.same_cols else 'csv')

def load_files(opt :LoadOptions):
    if Path(opt.database).exists():
        with closing(sqlite3.connect(opt.database)) as con:
            _load_files( Context(opt=opt, con=con, hdr=_load_db(con) ) )
    else:
        with TemporaryDirectory() as tempdir, closing(sqlite3.connect(Path(tempdir)/'toa5-merge.sqlite3')) as con:
            _init_db(con)
            try:
                _load_files( Context(opt=opt, con=con, hdr={}) )
            finally:
                with con:
                    con.execute('VACUUM INTO ?', (str(opt.database),))
                logger.log(NOTICE, 'Wrote database to %s', opt.database)

def merge_and_out(opt :MergeOptions):
    if opt.max_lsdelta<0:
        raise ValueError('max_lsdelta may not be negative')
    if opt.out_file and opt.out_file != '-' and Path(opt.out_file).exists():
        raise FileExistsError(opt.out_file)  # fail early, before doing work
    with closing(sqlite3.connect(opt.database)) as con:
        ctx = Context(opt=opt, con=con, hdr=_load_db(con) )
        hdr_merge = _prepare_header_merge(ctx)
        _check_dupe_rows(ctx)
        _write_out(ctx, hdr_merge)
