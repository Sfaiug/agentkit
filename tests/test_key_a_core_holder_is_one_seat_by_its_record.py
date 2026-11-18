"""A seat holding a core in scopes launched under two of its names is one row of `ak run status`,
under the name it has by then: renamed between the readings of the two, to a new name or back to
the second; and still, once one name led to the other, while a rename back has both hold its
record.  Two seats are two rows, whatever their records share.

Black-box, as tests/test_key_a_core_holder_renamed_meanwhile.py stages it.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_a_core_holder_renamed_meanwhile import held

RECORD = {"created": 1800000000.5, "cwd": "/work/acme"}
ONE_SEAT = {"parser": RECORD, "fix-api": {"renamed": "parser"}}


class ACoreHolderIsOneSeatByItsRecord(unittest.TestCase):
    def test_scopes_launched_under_two_names_of_a_seat_renamed_between_them_are_one_row(self):
        self.assertEqual(held(self, [("parser", 180), ("fix-api", 360)], ONE_SEAT, "parser",
                              {"scanner": RECORD, "parser": {"renamed": "scanner"}}),
                         ["seats holding 0.5 of a core or more: scanner 9m"])

    def test_they_are_one_row_renamed_back_to_the_second_between_them(self):
        # as first read each name leads to itself: parser before the rename, fix-api after
        self.assertEqual(held(self, [("parser", 180), ("fix-api", 360)], ONE_SEAT, "parser",
                              {"fix-api": RECORD, "parser": {"renamed": "fix-api"}}),
                         ["seats holding 0.5 of a core or more: fix-api 9m"])

    def test_they_stay_one_row_between_the_two_writes_of_a_rename_back(self):
        # the record is written to the new name first, the pointer to the old one after: between
        # the two neither name leads to the other
        self.assertEqual(held(self, [("fix-api", 180), ("parser", 360)], ONE_SEAT, "fix-api",
                              {"fix-api": RECORD}),
                         ["seats holding 0.5 of a core or more: parser 9m"])

    def test_two_seats_whose_records_match_are_two_rows(self):
        self.assertEqual(held(self, [("fix-api", 180), ("parser", 360)],
                              {"fix-api": RECORD, "parser": RECORD}),
                         ["seats holding 0.5 of a core or more: fix-api 9m · parser 6m"])


if __name__ == "__main__":
    unittest.main()
