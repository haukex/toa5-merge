TOA5 Merge Tool
===============

Command-line tool to merge multiple TOA5 files, possibly with differing columns, into a single file.

Building
--------

Requirements: Python 3.14, and
the following instructions assume a `bash` or compatible shell and GNU `make` being available.

- Clone this repository, then change into its directory
- `python3.14 -m venv .venv3.14` (adjust `python3.14` as necessary for your system)
- `. .venv3.14/bin/activate` (on Windows, use `Scripts` instead of `bin`)
- `make installdeps`
- If you want to run tests, run `make coverage`
- To build an `.exe` on Windows, run `make exe`; builds into `dist` folder
- To clean, `git clean -dxf -e '.venv*'`

For details, see <https://github.com/haukex/my-py-template/blob/main/dev/DevNotes.md>

Usage
-----

This assumes you've built the `.exe` and have that in your current working directory.
If instead you're just executing from the repository, use `python3 -m toa5_merge` instead of
`toa5-merge` in the following. In a *NIX shell, you may need to use `./toa5-merge`.

To get help:

- `toa5-merge --help`
- `toa5-merge db load --help` (where `db` is just a dummy placeholder)
- `toa5-merge db merge --help`


<!-- spell-checker: ignore installdeps -->

Author, Copyright, and License
------------------------------

Copyright (c) 2025-2026 Hauke Dämpfling (haukex@zero-g.net)
at the Leibniz Institute of Freshwater Ecology and Inland Fisheries (IGB),
Berlin, Germany, <https://www.igb-berlin.de/>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.