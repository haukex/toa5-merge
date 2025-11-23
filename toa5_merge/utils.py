"""
Utilities for :mod:`toa5_merge`
===============================

Author, Copyright, and License
------------------------------

Copyright (c) 2025 Hauke Dämpfling (haukex@zero-g.net)
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
from collections import deque
from collections.abc import Generator, Iterable, Hashable, Collection
from itertools import tee, islice, combinations
from graphlib import TopologicalSorter
from typing import TypeVar
import csv
import _csv  # just for types

# spell-checker: ignore appendleft

# borrowed from csv module's definitions:
_DialectLike = str | _csv.Dialect | csv.Dialect | type[_csv.Dialect | csv.Dialect]
def dual_csv_reader(fh :Iterable[str], /, dialect :_DialectLike = "excel", **fmt_params
                    ) -> tuple[Generator[list[str], None, None], Generator[str, None, None]]:
    """Returns two generators: the first is the standard ``csv.reader`` output,
    the second yields the raw data from the input file that produced the parsed output.
    As in the ``csv`` module, the file should be opened with ``newline=''``!

    For best efficiency it is strongly recommended to keep the generators mostly in sync,
    that is, always read one entry from the *csv reader*, then one from the *raw reader*,
    and so on - reading ahead a *few* entries on the *csv reader* is probably fine.

    Reading the *raw reader* before the *csv reader* causes the iteration of both readers
    to abort with an ``IndexError``."""
    fh_csv, fh_raw = tee(fh)
    csv_rd = csv.reader(fh_csv, dialect, **fmt_params)
    q :deque[str] = deque()
    done :bool = False
    def gen_csv() -> Generator[list[str], None, None]:
        nonlocal done
        prev_line = 0
        for row in csv_rd:
            q.appendleft( ''.join(islice(fh_raw, csv_rd.line_num-prev_line)) )
            prev_line = csv_rd.line_num
            yield row
            if done:  # signal from gen_raw
                raise IndexError('must read csv reader before raw reader')
        done = True  # signal to gen_raw
    def gen_raw() -> Generator[str, None, None]:
        nonlocal done
        while not done:  # signal from gen_csv
            if not q:
                done = True  # signal to gen_csv
                # use IndexError because that's what deque.pop would throw
                raise IndexError('must read csv reader before raw reader')
            yield q.pop()
    return gen_csv(), gen_raw()

_T = TypeVar('_T', bound=Hashable)
def find_superset(col_sets :Collection[Collection[_T]]) -> frozenset[_T]|None:
    fs = frozenset(map(frozenset, col_sets))
    if not fs:
        return None
    if len(fs)<2:
        return frozenset(next(iter(fs)))
    graph :TopologicalSorter[frozenset[_T]] = TopologicalSorter()
    for a, b in combinations(fs, 2):
        if a>b:
            graph.add(a,b)
        elif b>a:
            graph.add(b,a)
        else:
            graph.add(a)
            graph.add(b)
    order = list(graph.static_order())
    assert fs==frozenset(order), fs-frozenset(order)
    best = order[-1]
    return best if all( best.issuperset(s) for s in fs ) else None
