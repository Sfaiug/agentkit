"""A seat renamed while `ak run status` reads who holds a core
(tests/test_key_a_seat_holding_a_core_shows_in_status.py) is named once, with the longest of its
scopes, not under both names.

Black-box: the seat's state file is a pipe, so the test knows when the program reads it, and
puts the renamed seat's file in its place before that reading gets what the file held until
then.  A program asking for one seat's name twice gets both.  No wait is real.
"""

import json
import os
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home


class ACoreHolderRenamedMeanwhile(unittest.TestCase):
    def test_two_scopes_of_one_seat_renamed_between_them_are_one_row(self):
        with Home() as home:
            home.write(".agentkit/state/watch.json", {"seat_cores": {
                "agentkit-seat-fix-api-89abcdef.scope": {"at": 720, "since": 180},
                "agentkit-seat-fix-api-0123abcd.scope": {"at": 720, "since": 360}}})
            seat = home.path / ".agentkit/state/session-fix-api.json"
            os.mkfifo(seat)
            renamed = home.root / "renamed"
            renamed.write_text(json.dumps({"renamed": "parser"}))

            def rename():
                with seat.open("w") as read:    # opens once the program reads the file
                    os.replace(renamed, seat)
                    read.write("{}")

            # a daemon: a program that never reads the file leaves it waiting
            threading.Thread(target=rename, daemon=True).start()
            done = home.ak("run", "status")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual([line for line in done.out.splitlines()
                          if line.startswith("seats holding a core")],
                         ["seats holding a core: fix-api 9m"])


if __name__ == "__main__":
    unittest.main()
