"""A seat renamed while `ak run status` reads who holds a core
(tests/test_key_a_seat_holding_a_core_shows_in_status.py) is named once, with the longest of its
scopes, not under both names.

Black-box: a seat's state file is a pipe, so the test knows when the program reads it, and
writes what the rename leaves before that reading gets what the file held until then.  A
program asking for one seat's name twice gets both.  No wait is real.
"""

import os
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home


def held(scopes, records, pipe=None, renamed=None):
    """Who `ak run status` says holds a core, over those scopes' (seat, since) and the seats'
    state files `records`; `renamed`'s are written once it reads seat `pipe`'s."""
    with Home() as home:
        home.write(".agentkit/state/watch.json", {"seat_cores": {
            f"agentkit-seat-{seat}-{index:08x}.scope": {"at": 720, "since": since}
            for index, (seat, since) in enumerate(scopes)}})
        for seat, record in records.items():
            home.write(f".agentkit/state/session-{seat}.json", record)
        if pipe:
            read = home.path / f".agentkit/state/session-{pipe}.json"
            os.mkfifo(read)

            def rename():
                with read.open("w") as reading:     # opens once the program reads the file
                    read.unlink()
                    for seat, record in renamed.items():
                        home.write(f".agentkit/state/session-{seat}.json", record)
                    reading.write("{}")

            # a daemon: a program that never reads the file leaves it waiting
            threading.Thread(target=rename, daemon=True).start()
        done = home.ak("run", "status")
    assert done.code == 0, done.err
    return [line.partition(": ")[2] for line in done.out.splitlines()
            if line.startswith("seats holding ")]


class ACoreHolderRenamedMeanwhile(unittest.TestCase):
    def test_two_scopes_of_one_seat_renamed_between_them_are_one_row(self):
        self.assertEqual(held([("fix-api", 180), ("fix-api", 360)], {}, "fix-api",
                              {"fix-api": {"renamed": "parser"}}), ["parser 9m"])

    def test_two_scopes_of_one_seat_renamed_while_another_is_read_are_one_row(self):
        self.assertEqual(held([("fix-api", 180), ("acme", 540), ("fix-api", 360)], {}, "acme",
                              {"fix-api": {"renamed": "parser"}}), ["parser 9m · acme 3m"])


if __name__ == "__main__":
    unittest.main()
