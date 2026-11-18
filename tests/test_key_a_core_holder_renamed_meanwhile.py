"""A seat renamed while `ak run status` reads who holds a core
(tests/test_key_a_seat_holding_a_core_shows_in_status.py) is named once, with the longest of its
scopes, not under both names.

Black-box: the seat's state file is a pipe, so the test knows when the program reads it, and
puts the renamed seat's file in its place before that reading gets what the file held until
then.  A program asking for the seat's name once for each scope gets both.  No wait is real.
"""

import json
import os
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home


def held(test, scopes, files, pipe=None, renamed=None):
    """The lines of `ak run status` naming who holds a core, over those scopes' (seat, since) and
    those seats' state files.  Seat `pipe`'s is a pipe: once the program reads it, `renamed`'s
    are in place before that reading gets what the file held until then."""
    with Home() as home:
        home.write(".agentkit/state/watch.json", {"seat_cores": {
            f"agentkit-seat-{seat}-{index:08x}.scope": {"at": 720, "since": since}
            for index, (seat, since) in enumerate(scopes)}})
        for seat, record in files.items():
            home.write(f".agentkit/state/session-{seat}.json", record)
        if pipe:
            read = home.path / f".agentkit/state/session-{pipe}.json"
            read.unlink()
            os.mkfifo(read)

            def rename():
                with read.open("w") as reading:     # opens once the program reads the file
                    read.unlink()
                    for seat, record in renamed.items():
                        home.write(f".agentkit/state/session-{seat}.json", record)
                    reading.write(json.dumps(files[pipe]))

            # a daemon: a program that never reads the file leaves it waiting
            threading.Thread(target=rename, daemon=True).start()
        done = home.ak("run", "status")
    test.assertEqual(done.code, 0, done.err)
    return [line for line in done.out.splitlines() if line.startswith("seats holding ")]


class ACoreHolderRenamedMeanwhile(unittest.TestCase):
    def test_two_scopes_of_one_seat_renamed_between_them_are_one_row(self):
        self.assertEqual(held(self, [("fix-api", 180), ("fix-api", 360)], {"fix-api": {}},
                              "fix-api", {"fix-api": {"renamed": "parser"}}),
                         ["seats holding 0.5 of a core or more: parser 9m"])     # its name by then


if __name__ == "__main__":
    unittest.main()
