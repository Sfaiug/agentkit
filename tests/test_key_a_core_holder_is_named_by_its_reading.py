"""`ak run status` names a seat holding a core (tests/test_key_a_seat_holding_a_core_shows_in_status.py)
as the tick's reading named it, once for all its scopes: it asks for no seat's name itself, so a
rename under way cannot show one seat under two.

Black-box: the reading names a seat `parser` whose scopes launched as `fix-api`, and no seat's
file is there to ask.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home


class ACoreHolderIsNamedByItsReading(unittest.TestCase):
    def test_two_scopes_the_reading_named_alike_are_one_row_under_that_name(self):
        with Home() as home:
            home.write(".agentkit/state/watch.json", {"seat_cores": {
                "agentkit-seat-fix-api-89abcdef.scope": {"at": 720, "since": 180, "seat": "parser"},
                "agentkit-seat-fix-api-0123abcd.scope": {"at": 720, "since": 360, "seat": "parser"},
                "agentkit-seat-acme-4567abcd.scope": {"at": 720, "since": 360}}})
            done = home.ak("run", "status")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual([line for line in done.out.splitlines()
                          if line.startswith("seats holding a core")],
                         ["seats holding a core: parser 9m"])


if __name__ == "__main__":
    unittest.main()
