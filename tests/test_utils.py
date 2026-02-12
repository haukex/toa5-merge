"""
Tests for :mod:`toa5_merge.utils`
=================================

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
import unittest
import toa5_merge.utils as uut

class TestUtils(unittest.TestCase):

    def test_dual_csv_reader(self):
        f = io.StringIO('a,b,c\r\n"A\nA",B," C "\n"D,D",,F F', newline='')
        csv_it, raw_it = uut.dual_csv_reader(f, strict=True)
        self.assertEqual( next(csv_it), ["a","b","c"] )
        self.assertEqual( next(raw_it), 'a,b,c\r\n' )
        self.assertEqual( next(csv_it), ["A\nA","B"," C "] )
        self.assertEqual( next(csv_it), ["D,D","","F F"] )
        self.assertEqual( next(raw_it), '"A\nA",B," C "\n' )
        self.assertEqual( next(raw_it), '"D,D",,F F' )
        with self.assertRaises(StopIteration):
            next(csv_it)
        with self.assertRaises(StopIteration):
            next(raw_it)
        f.seek(0)
        csv_it, raw_it = uut.dual_csv_reader(f, strict=True)
        self.assertEqual( next(csv_it), ["a","b","c"] )
        self.assertEqual( next(raw_it), 'a,b,c\r\n' )
        with self.assertRaises(IndexError):
            next(raw_it)
        with self.assertRaises(IndexError):
            next(csv_it)

    def test_find_superset(self):
        self.assertEqual( uut.find_superset([
            {1,2,3,4,5,    8,9},
            {1,2,3,4,5,6,7,8,9},
            {1,2,3,4,5,6,7,8,9},
            {1,  3,4,5,6,7,8,9},
            {  2,3,4,5,6,7,8,9},
            {1,2,3,4,5,    8,9},
            {1,2,3,4,5,6,7    },
            {1,2,3,4,5        },
            {1,2,3,  5        },
            {1,2,3,4          },
            {1,2,3,4,      8,9},
            {1,2,3,4          },
        ]), {1,2,3,4,5,6,7,8,9} )
        self.assertIsNone( uut.find_superset([
            {0,1,2,3,4          },
            {0,1                },
            {    2,3            },
            {0,  2,3,4          },
            {         5,6,7,8,9},
            {                8,9},
            {          5,6,7    },
            {            6,  8,9},
        ]) )
        self.assertIsNone( uut.find_superset([
            {0,1,2,3,4,5,6      },
            {      3,4,5,6,7,8,9},
        ]) )
        self.assertIsNone( uut.find_superset([
            {0,1,2,3,4          },
            {0,                9},
            {          5,6,7,8,9},
        ]) )
        self.assertIsNone( uut.find_superset([
            {0,1,2,3,4,5,6      },
            {      3,4,5,6,7,8,9},
            {0,1,2,3,    6,7,8,9},
        ]) )
        self.assertEqual( uut.find_superset([
            {0,1,2,3,4          },
            {0,                9},
            {          5,6,7,8,9},
            {0,1,2,3,4,5,6,7,8,9},
        ]), {0,1,2,3,4,5,6,7,8,9} )
        self.assertIsNone( uut.find_superset([ {1}, {2} ]) )
        self.assertEqual( uut.find_superset([ {0,1}, {0} ]), {0,1} )
        self.assertEqual( uut.find_superset([ {0,1,2} ]), {0,1,2} )
        self.assertEqual( uut.find_superset([ {0,1,2}, {0,1,2} ]), {0,1,2} )
        self.assertIsNone( uut.find_superset([]) )
