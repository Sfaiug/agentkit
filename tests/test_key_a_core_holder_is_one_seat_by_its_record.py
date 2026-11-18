"""Scopes launched under two names are one row of `ak run status` where they are one seat's: a
seat renamed while it reads, under the name it has by then, and one between a rename's two
writes, while both names hold its record.  Two seats are two rows, whatever their records share.

Black-box, as tests/test_key_a_core_holder_renamed_meanwhile.py stages it.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_a_core_holder_renamed_meanwhile import held

MADE = 1800000000.5


class ACoreHolderIsOneSeatByItsRecord(unittest.TestCase):
    def test_a_seat_renamed_between_its_two_launch_names_is_one_row_under_its_new_name(self):
        # as `ak orch rename` leaves an unnamed seat: its record under the new name, changed
        self.assertEqual(
            held([("fix-api", 180), ("acme", 540), ("parser", 360)],
                 {"fix-api": {"renamed": "parser"}, "parser": {"created": MADE, "unnamed": True}},
                 "acme", {"scanner": {"created": MADE}, "parser": {"renamed": "scanner"},
                          "fix-api": {"renamed": "scanner"}}),
            ["scanner 9m · acme 3m"])

    def test_a_seat_whose_rename_is_half_written_is_one_row(self):
        self.assertEqual(held([("fix-api", 180), ("parser", 360), ("acme", 540)],
                              {"fix-api": {"created": MADE}, "parser": {"created": MADE},
                               "acme": {"created": 9.5}}), ["fix-api 9m · acme 3m"])

    def test_two_seats_made_at_one_moment_are_two_rows(self):
        self.assertEqual(held([("fix-api", 180), ("parser", 360)],
                              {"fix-api": {"created": MADE, "cwd": "/work/fix-api"},
                               "parser": {"created": MADE, "cwd": "/work/parser"}}),
                         ["fix-api 9m · parser 6m"])

    def test_seats_whose_records_say_no_moment_they_were_made_at_are_a_row_each(self):
        self.assertEqual(held([("fix-api", 180), ("parser", 360), ("acme", 540)],
                              {"fix-api": {}, "parser": {}, "acme": {"created": [1]}}),
                         ["fix-api 9m · parser 6m · acme 3m"])


if __name__ == "__main__":
    unittest.main()
