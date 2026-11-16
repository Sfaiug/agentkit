"""A run repairing its line's target is first in that line, behind its green deliveries only.

Three runs wait in the line to land on main, and a repair of main, whose record holds the
`repair` ak gives it, joined after them: `ak run status` reads the repair first in line and
the others behind it in join order.  A green delivery, its stack tested, stays ahead of it, and
two repairs keep their join order.

Black-box: the runs are records written by hand where ak keeps them, and the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py; this test fails against `/bin/false`.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from test_key_waiting_run_says_where_it_waits import lock, record, wait_lines

WAITING = ["20261116-1001-fix-api", "20261116-1002-fix-docs", "20261116-1003-fix-ui"]
REPAIR = "20261116-1004-repair-main"
FLAKY = "20261116-1005-repair-clock"
PLACES = "1st 2nd 3rd 4th 5th".split()


class RepairIsFirstInItsLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.now = time.time()
        for minute, run in enumerate(WAITING, start=1):
            self.join(run, minute)
        self.join(REPAIR, 4, repair={"target": "main", "command": "python3 tests/test_widget.py"})

    def join(self, run, minute, wait=None, **fields):
        record(self.home, run, state="waiting", base="origin/main", target="origin/main",
               started_at=self.now - 3600, round_summaries=[{}], **fields,
               waiting_on={"line": lock("main"), "joined": self.now - 600 + 60 * minute,
                           **(wait or {})})

    def assertPlaces(self, order):
        done = self.home.ak("run", "status")
        self.assertEqual(done.code, 0, done.err)
        said = wait_lines(done.out)
        self.assertEqual({run: said.get(run) for run in order},
                         {run: [f"waiting · {place} in line to land on main"]
                          for run, place in zip(order, PLACES)})

    def test_the_repair_that_joined_last_is_first(self):
        self.assertPlaces([REPAIR, *WAITING])

    def test_a_green_delivery_stays_ahead_of_it(self):
        self.join(WAITING[2], 3, wait={"land": "a" * 40})
        self.assertPlaces([WAITING[2], REPAIR, *WAITING[:2]])

    def test_two_repairs_keep_their_join_order(self):
        self.join(FLAKY, 5, repair={"target": "main", "command": "tests/test_clock.py",
                                    "flaky": self.now - 900})
        self.assertPlaces([REPAIR, FLAKY, *WAITING])


if __name__ == "__main__":
    unittest.main()
