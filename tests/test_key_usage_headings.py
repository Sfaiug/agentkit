"""`ak usage`'s table, where it fits whole, opens with its headings in their order, and a login's
row has a cell under each.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, one login with a week read, on a terminal wide enough for
the whole table.  Fails against /bin/false.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

HEADINGS = ("provider", "model(s)", "left", "a month", "resets", "week elapsed", "session",
            "resets held", "headroom", "budget", "outlook")


class UsageHeadings(unittest.TestCase):
    def test_a_wide_table_opens_with_its_headings_and_a_row_has_a_cell_under_each(self):
        with Home() as home:
            meters.install(home).week("acme", used=40)
            akconfig.write(home, {"anvil": {"harness": "echo", "provider": "acme"}})
            done = home.ak("usage", env={"COLUMNS": "200"})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(done.out.splitlines()[0].split(), " ".join(HEADINGS).split(), done.out)
        for heading in HEADINGS:
            with self.subTest(heading):
                self.assertNotEqual(meters.cell(done.out, "Acme", heading), "", done.out)


if __name__ == "__main__":
    unittest.main()
