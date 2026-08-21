"""
Tests for :mod:`toa5_merge`
===========================

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
import json
import sqlite3
import logging
import unittest
from pathlib import Path
from typing import override
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta
from contextlib import redirect_stdout, closing
from more_itertools import one, strictly_n
from igbpyutils.file import Filename
import toa5_merge as uut

PATH = Path(__file__).parent/'toa5'

class TestToa5Merge(unittest.TestCase):

    @override
    def setUp(self) -> None:
        self.maxDiff = None  # pylint: disable=invalid-name

    def _check_basic_load_logs(self, lcm_output :list[str]):
        # Data_bad1.dat.gz: Headers end within quoted field on second line (also compressed for code coverage)
        one( s for s in lcm_output if re.match(r'^WARNING:toa5-merge:Skipping\b.+\bData_bad1\.dat\b.+due to\b.+\bToa5Error\b', s) )
        # Data_bad2.dat: Header ok, second data row ends within quoted field
        one( s for s in lcm_output if
            re.match(r'^WARNING:toa5-merge:Stopped parsing\b.+\bData_bad2\.dat\b.+\bat row 5\b.+due to\b.+\b_?csv\.Error\b', s) )
        # Data_bad3.dat: Header ok, second data row ends after timestamp, so column count mismatch
        one( s for s in lcm_output if
            re.match(r'^WARNING:toa5-merge:Skipping bad row 6 in\b.+\bData_bad3\.dat\b.+\bdue to column count mismatch\b', s) )
        self.assertGreater( sum( 1 for s in lcm_output if re.match(r'DEBUG:toa5-merge:Skipping\b.+\bdue to filter$', s) ), 8 )

    def _check_basic_merge_logs(self, lcm_output :list[str]):
        one( s for s in lcm_output if s == 'INFO:toa5-merge:Found this one header that includes all 4 columns:\n'
            '"TOA5","MyLogger","CR1000X","1234","CR1000X.Std.06.00","CPU:MyProgram.CR1X","3457","Data"' )
        one( s for s in lcm_output if s == 'NOTICE:toa5-merge:The following environment line(s) will be lost in the merge:\n'
            '"TOA5","MyLogger","CR1000X","1234","CR1000X.Std.06.00","CPU:MyProgram.CR1X","3456","Data"\n'
            '"TOA5","MyLogger","CR1000X","1234","CR1000X.Std.06.00","CPU:MyProgram.CR1X","3458","Data"')
        list(strictly_n(( s for s in lcm_output if re.match(r'\ADEBUG:toa5-merge:Column map for hid \d+: \[0, 1, 2, None\]\Z',s) ), 2 ))
        one( s for s in lcm_output if re.match(r'\ADEBUG:toa5-merge:Column map for hid \d+: \[0, 1, 2, 3\]\Z',s) )
        one( s for s in lcm_output if re.match(r'\AINFO:toa5-merge:Marked 1 of \d+ total rows as duplicates \(1 with an lsdelta\)\Z', s) )

    def _check_db(self, dbf :Filename, *, dupes_checked :bool):
        with closing(sqlite3.connect(dbf)) as con:
            exp_h = [
                '"TOA5","MyLogger","CR1000X","1234","CR1000X.Std.06.00","CPU:MyProgram.CR1X","3456","Data"\n'
                '"TIMESTAMP","RECORD","BattV_Min"\n'  '"TS","RN","Volts"\n'  '"","","Min"',
                '"TOA5","MyLogger","CR1000X","1234","CR1000X.Std.06.00","CPU:MyProgram.CR1X","3457","Data"\n'
                '"TIMESTAMP","RECORD","BattV_Min","BattV_Avg"\n'  '"TS","RN","Volts","Volts"\n'  '"","","Min","Avg"',
                '"TOA5","MyLogger","CR1000X","1234","CR1000X.Std.06.00","CPU:MyProgram.CR1X","3458","Data"\n'
                '"TIMESTAMP","RECORD","BattV_Min"\n'  '"TS","RN","Volts"\n'  '"","","Min"' ]
            got_h = [ r[0] for r in con.execute('SELECT header FROM headers ORDER BY header') ]
            self.assertEqual(got_h, exp_h)
            exp_f = [
                (json.dumps(f.name), 0 if f.name=='Data_bad2.dat' else f.stat().st_size, int(f.stat().st_mtime)) for f in
                (PATH/'Data1.dat', PATH/'Data2.dat', PATH/'Data3.dat', PATH/'Data4.dat',
                 PATH/'Data_bad1.dat.gz', PATH/'Data_bad2.dat', PATH/'Data_bad3.dat') ]
            got_f = con.execute('SELECT filename, size, mtime FROM files ORDER BY filename').fetchall()
            self.assertEqual(got_f, exp_f)
            exp_r :list[tuple[str,str,str,str,str,int]] = [
                ( exp_f[0][0], exp_h[0], '"2025-11-04 15:30:00",1,13.83', '["2025-11-04 15:30:00","1","13.83"]', '2025-11-04 15:30:00', 0 ),
                ( exp_f[0][0], exp_h[0], '"2025-11-04 15:40:00",3,13.76', '["2025-11-04 15:40:00","3","13.76"]', '2025-11-04 15:40:00', 0 ),

                ( exp_f[1][0], exp_h[1], '"2025-11-04 15:35:00",2,13.80,12.98', '["2025-11-04 15:35:00","2","13.80","12.98"]',
                    '2025-11-04 15:35:00', 0 ),
                ( exp_f[1][0], exp_h[1], '"2025-11-04 15:50:00",3,13.76,12.99', '["2025-11-04 15:50:00","3","13.76","12.99"]',
                    '2025-11-04 15:50:00', 0 ),

                ( exp_f[2][0], exp_h[0], '"2025-11-04 15:30:00",1,13.83',  '["2025-11-04 15:30:00","1","13.83"]',  '2025-11-04 15:30:00', 0 ),
                ( exp_f[2][0], exp_h[0], '"2025-11-04 15:40:00",3,13.76',  '["2025-11-04 15:40:00","3","13.76"]',  '2025-11-04 15:40:00', 0 ),
                ( exp_f[2][0], exp_h[0], '"2025-11-04 15:40:00",3,13.761', '["2025-11-04 15:40:00","3","13.761"]', '2025-11-04 15:40:00',
                    1 if dupes_checked else 0 ),
                ( exp_f[2][0], exp_h[0], '"2025-11-04 15:45:00",4,13.56',  '["2025-11-04 15:45:00","4","13.56"]',  '2025-11-04 15:45:00', 0 ),
                ( exp_f[3][0], exp_h[2], '"2025-11-04 15:45:00",4,13.56', '["2025-11-04 15:45:00","4","13.56"]', '2025-11-04 15:45:00', 0 ),
                ( exp_f[3][0], exp_h[2], '"2025-11-04 16:00:00",5,13.41', '["2025-11-04 16:00:00","5","13.41"]', '2025-11-04 16:00:00', 0 ),
                ( exp_f[3][0], exp_h[2], '"2025-11-04 16:15:00",6,13.22', '["2025-11-04 16:15:00","6","13.22"]', '2025-11-04 16:15:00', 0 ),
                ( exp_f[3][0], exp_h[2], '"2025-11-04 16:30:00",7,"NAN"', '["2025-11-04 16:30:00","7","NAN"]', '2025-11-04 16:30:00', 0 ),

                ( exp_f[6][0], exp_h[0], '"2025-11-04 15:30:00",1,13.83', '["2025-11-04 15:30:00","1","13.83"]', '2025-11-04 15:30:00', 0 ),
            ]
            got_r = con.execute('''
                SELECT f.filename, h.header, r.raw_row, r.json_row, r.key, r.is_dupe
                FROM     rows AS r
                JOIN row2file AS r2f ON r.id = r2f.rid
                JOIN    files AS f   ON r2f.fid = f.id
                JOIN  headers AS h   ON h.id = r.hid
                ORDER BY f.filename, h.header, r.raw_row
            ''').fetchall()
            self.assertEqual(got_r, exp_r)

    def test_basic(self):
        # Data[1-4].dat: normal data files (Data2.dat has an additional column)
        with TemporaryDirectory() as td:
            dbf = Path(td)/'x.sqlite3'

            # load
            with self.assertLogs(level=logging.DEBUG) as lcm:
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='Data'))
            self._check_basic_load_logs(lcm.output)
            self._check_db(dbf, dupes_checked=False)

            # check seen file skipping
            with self.assertLogs(level=logging.DEBUG) as lcm:
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='Data'))
            self._check_basic_load_logs(lcm.output)
            self.assertFalse( [ s for s in lcm.output if 'already in DB' in s ] )
            self._check_db(dbf, dupes_checked=False)
            # for coverage, need to force the matcher to execute once for a file inside of an archive, so remove one from the "seen" list
            with closing(sqlite3.connect(dbf)) as con:
                with con:
                    con.execute(''' DELETE FROM files WHERE filename='"Data_bad1.dat.gz"' ''')
            with self.assertLogs(level=logging.DEBUG) as lcm:
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='Data', skip_seen=True))
            self.assertEqual( len([ s for s in lcm.output if 'already in DB' in s ]), 5 )
            self._check_db(dbf, dupes_checked=False)

            # merge basic
            with redirect_stdout(io.StringIO()) as out, self.assertLogs(level=logging.DEBUG) as lcm:
                uut.merge_and_out(uut.MergeOptions(database=dbf, max_lsdelta=1))
            self._check_basic_merge_logs(lcm.output)
            self.assertEqual( out.getvalue().replace('\r\n','\n').replace('\r','\n').rstrip('\n'),
                            (PATH/'exp_out_Data.txt').read_text(encoding='ASCII').rstrip('\n') )
            self._check_db(dbf, dupes_checked=True)

            # merge with drop_dupes and out_file
            out_f = Path(td)/'output.txt'
            with redirect_stdout(io.StringIO()) as out, self.assertLogs(level=logging.DEBUG) as lcm:
                uut.merge_and_out(uut.MergeOptions(database=dbf, max_lsdelta=1, drop_dupes=True, out_file=out_f))
                with self.assertRaises(FileExistsError):
                    uut.merge_and_out(uut.MergeOptions(database=dbf, max_lsdelta=1, drop_dupes=True, out_file=out_f))
            self._check_basic_merge_logs(lcm.output)
            self.assertEqual( out_f.read_text(encoding='ASCII').rstrip('\n'),
                              (PATH/'exp_out_Data_dd.txt').read_text(encoding='ASCII').rstrip('\n') )
            self.assertEqual(out.getvalue(), '')
            self._check_db(dbf, dupes_checked=True)

            # merge with no max_lsdelta
            with self.assertLogs(level=logging.DEBUG), self.assertRaises(uut.MergeError):
                uut.merge_and_out(uut.MergeOptions(database=dbf))

            # merge with bad max_lsdelta
            with self.assertRaises(ValueError), self.assertNoLogs(level=logging.DEBUG):
                uut.merge_and_out(uut.MergeOptions(database=dbf, max_lsdelta=-1))

            self._check_db(dbf, dupes_checked=True)

            # load a file without TIMESTAMP column
            with self.assertLogs(level=logging.DEBUG), self.assertRaises(NotImplementedError):
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='Other'))

    def test_db_bad_version(self):
        with TemporaryDirectory() as td:
            dbf = Path(td)/'x.sqlite3'
            with closing(sqlite3.connect(dbf)) as con:
                con.execute('PRAGMA user_version=-1')
            with self.assertNoLogs(), self.assertRaises(sqlite3.DatabaseError):
                uut.load_files(uut.LoadOptions(database=dbf, paths=[]))
            with self.assertNoLogs(), self.assertRaises(sqlite3.DatabaseError):
                uut.merge_and_out(uut.MergeOptions(database=dbf))

    def test_batch_commit(self):
        with closing(sqlite3.connect(':memory:')) as con, self.assertLogs(level=logging.DEBUG) as lcm:
            ctx = uut.Context(opt=uut.LoadOptions(database=':memory:', paths=()), con=con, hdr={})
            uut._init_db(con)  # pylint: disable=protected-access  # pyright: ignore [reportPrivateUsage]
            def file_gen(count :int):
                yield '"TOA5","MyLogger","CR1000X","1234","CR1000X.Std.06.00","CPU:MyProgram.CR1X","3456","Data"\r\n'
                yield '"TIMESTAMP","RECORD","BattV_Min"\r\n'
                yield '"TS","RN","Volts"\r\n'
                yield '"","","Min"\r\n'
                d = timedelta(minutes=5)
                dt = datetime(2025,5,5,15)
                for rn in range(1,count+1):
                    yield f'"{dt.strftime('%Y-%m-%d %H:%M:%S')}",{rn},12.345\r\n'
                    dt += d
            uut._load_file(  # pylint: disable=protected-access  # pyright: ignore [reportPrivateUsage]
                ctx, uut.FileInfo(names=(), size=None, mtime=None), file_gen(11000))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM rows').fetchone()[0], 11000)
        one( s for s in lcm.output if s == 'INFO:toa5-merge:Loaded 9996 rows from [] so far...' )

    def test_merge_errors(self):
        # One: Same timestamps, but second file has an additional column, which means the values from that column don't match
        # Two: Same timestamp but values outside of lsdelta
        # Three: Same timestamp but one of the values isn't a number so lsdelta fails
        # Four: No common super header that includes all columns
        for tbl in 'One', 'Two', 'Three', 'Four':
            with TemporaryDirectory() as td:
                dbf = Path(td)/'x.sqlite3'
                with self.assertLogs(level=logging.DEBUG):
                    uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name=tbl))
                with self.assertLogs(level=logging.DEBUG) as lcm, self.assertRaises(uut.MergeError):
                    uut.merge_and_out(uut.MergeOptions(database=dbf, max_lsdelta=1))
                if tbl=='Four':
                    one( s for s in lcm.output if re.match(r'\AWARNING:toa5-merge:Here are the headers I have:$',s,re.M) )

    def test_merge_error2(self):
        # Test a tricky case: Cols1.dat and Cols2.dat contain a row that looks identical, but actually isn't due to the column headers!
        with TemporaryDirectory() as td:
            dbf = Path(td)/'x.sqlite3'
            with self.assertLogs(level=logging.DEBUG):
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='Cols'))
            with self.assertLogs(level=logging.DEBUG), self.assertRaises(uut.MergeError) as ecm:
                uut.merge_and_out(uut.MergeOptions(database=dbf, max_lsdelta=1))
            self.assertTrue( str(ecm.exception).startswith(
                'Found a row with the same timestamp but different values (max_lsdelta=1):\n'
                "key='2025-11-04 15:30:00' is shared by:\n" ), str(ecm.exception) )
            self.assertIn( '''\n    row='"2025-11-04 15:30:00",1,12.34,12.34' in files ['"Cols1.dat"']\n''', str(ecm.exception) )
            self.assertIn( '''\n    row='"2025-11-04 15:30:00",1,12.34,12.34' in files ['"Cols2.dat"']\n''', str(ecm.exception) )

    def test_merge_csv_fail(self):
        # Unsupported characters in CSV output
        with TemporaryDirectory() as td:
            dbf = Path(td)/'x.sqlite3'
            with self.assertLogs(level=logging.DEBUG):
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='CsvFail'))
            with redirect_stdout(io.StringIO()), self.assertLogs(level=logging.DEBUG), self.assertRaises(ValueError) as ecm:
                uut.merge_and_out(uut.MergeOptions(database=dbf))
            self.assertTrue( str(ecm.exception).startswith( "unsupported characters in field='x\"y'" ), str(ecm.exception) )

    def test_merge_multi_head(self):
        # Test for files that are numerically identical but the strings are not (e.g. scientific notation)
        # and where the merge results may be different based on the order in which they are merged.
        # (I consider this acceptable because such cases should be rare.)
        with TemporaryDirectory() as td:
            dbf = Path(td)/'x.sqlite3'
            with self.assertLogs(level=logging.DEBUG):
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='Multi'))

            for dd,exp_f in (True,('exp_out_Multi_A_dd.txt', 'exp_out_Multi_B_dd.txt')), (False,('exp_out_Multi_A.txt', 'exp_out_Multi_B.txt')):
                with redirect_stdout(io.StringIO()) as out, self.assertLogs(level=logging.DEBUG) as lcm:
                    uut.merge_and_out(uut.MergeOptions(database=dbf, max_lsdelta=1, drop_dupes=dd))
                self.assertIn( out.getvalue().replace('\r\n','\n').replace('\r','\n').rstrip('\n'),
                    [ (PATH/f).read_text(encoding='ASCII').rstrip('\n') for f in exp_f ] )
                one( s for s in lcm.output if
                    re.match(r'\AINFO:toa5-merge:Found more than one header that includes all 3 columns, arbitrarily using the last one:$',s,re.M) )
                one( s for s in lcm.output if re.match(r'\AINFO:toa5-merge:Marked 2 of \d+ total rows as duplicates \(1 with an lsdelta\)\Z', s) )

    def test_diff_env_lines(self):
        # Same[12].dat: Files that are identical *except* for the environment line
        # The same rows with the same column headers should be considered the same.
        with TemporaryDirectory() as td:
            dbf = Path(td)/'x.sqlite3'
            with self.assertLogs(level=logging.DEBUG):
                uut.load_files(uut.LoadOptions(database=dbf, paths=[PATH], table_name='Same'))
            with redirect_stdout(io.StringIO()) as out, self.assertLogs(level=logging.DEBUG) as lcm:
                uut.merge_and_out(uut.MergeOptions(database=dbf))
            self.assertIn( out.getvalue().replace('\r\n','\n').replace('\r','\n').rstrip('\n'),
                [ (PATH/f).read_text(encoding='ASCII').rstrip('\n') for f in ('Same1.dat','Same2.dat') ] )
            one( s for s in lcm.output if s == 'INFO:toa5-merge:Marked 0 of 8 total rows as duplicates (0 with an lsdelta)' )
