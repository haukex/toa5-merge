#!/usr/bin/env python
"""
Command-Line Interface for :mod:`toa5_merge`
============================================

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
import logging
import argparse
from operator import itemgetter
import igbpyutils.error
from igbpyutils.file import autoglob
from toa5_merge import load_files, LoadOptions, merge_and_out, MergeOptions

# spell-checker: ignore autoglob

def _arg_parser():
    parser = argparse.ArgumentParser('toa5_merge', description='TOA5 Merge Tool')
    parser.add_argument('-l', '--log-level', help="Logging level (default: INFO)",
        choices = [ str(s) for kv in sorted(logging.getLevelNamesMapping().items(), key=itemgetter(1)) for s in kv if kv[0]!='NOTSET' ],
        default = logging.getLevelName(logging.INFO) )
    parser.add_argument('database', metavar='DB_FILE', help="The sqlite3 database file to use")

    subparsers = parser.add_subparsers(dest='cmd', required=True, help='"toa5_merge db load/merge -h" for help')

    parser_load = subparsers.add_parser('load', help='Load TOA5 files into database')
    parser_load.add_argument('--station-name', help="Skip files that don't have this TOA5 station name")
    parser_load.add_argument('--table-name', help="Skip files that don't have this TOA5 table name")
    parser_load.add_argument('--program-sig', help="Skip files that don't have this TOA5 program signature")
    parser_load.add_argument('--logger-serial', help="Skip files that don't have this TOA5 logger serial number")
    parser_load.add_argument('--ignore-size', help="Ignore errors in files that are multiples of this size (default: 0=off)", type=int, default=0)
    parser_load.add_argument('--skip-seen', help="Skip files that are already in the database "
                             "(same relative name, size, and mtime; physical files only, not inside archives)",
                             action='store_true')
    parser_load.add_argument('paths', metavar="PATH", help="Paths/files to process recursively, incl. archives", nargs="+")

    parser_merge = subparsers.add_parser('merge', help='Output merged TOA5 from database')
    parser_merge.add_argument('--max-lsdelta', help="Maximum Delta in Least Significant digits (default: 0)", type=int, default=0)
    parser_merge.add_argument('--drop-dupes', help="Drop duplicates that are within lsdelta of each other", action='store_true')
    parser_merge.add_argument('-o', '--out-file', help="Output filename (default: STDOUT)")

    return parser

def main():
    igbpyutils.error.init_handlers(repeat_msg=True)
    parser = _arg_parser()
    args = parser.parse_args()
    igbpyutils.error.logging_config(level=int(args.log_level) if args.log_level.isdigit() else logging.getLevelNamesMapping()[args.log_level])
    match args.cmd:
        case 'load': load_files(LoadOptions(
            paths         = list(autoglob(args.paths)),
            database      = args.database,
            station_name  = args.station_name,
            table_name    = args.table_name,
            program_sig   = args.program_sig,
            logger_serial = args.logger_serial,
            ignore_size   = args.ignore_size,
            skip_seen     = args.skip_seen,
        ))
        case 'merge': merge_and_out(MergeOptions(
            database      = args.database,
            max_lsdelta   = args.max_lsdelta,
            drop_dupes    = args.drop_dupes,
            out_file      = args.out_file,
        ))
        case _: parser.error('bad command')  # for linter
    parser.exit(0)

if __name__=='__main__':  # pragma: no cover
    main()
