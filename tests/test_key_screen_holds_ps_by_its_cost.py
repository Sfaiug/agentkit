"""An open screen reads the process table less often the more a reading costs: at most
`open_runs.SHARE` of a core, and never staler than `open_runs.CEILING`.

With 615 processes one `ps` cost 0.19 s of CPU, and an open screen read it every 15 s.  Black-box:
the program `AK_BIN` names runs in a person's terminal (tests/fixtures/akterm.py) with a `ps`
first on its PATH that logs each call, takes COST seconds and runs the real one.  What holds a
reading inside a pass, and nowhere else, is tests/test_screen_holds_ps_by_its_cost.py.
"""

import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, SYSTEM, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

PS = shutil.which("ps", path=os.pathsep.join(SYSTEM))
COST = 0.3        # seconds a reading takes: held COST / SHARE, CEILING at most, where cheap is 10 s
HELD = 60         # open_runs.CEILING: the most a costly reading is held
WATCHED = 60      # seconds the screen stays open, woken every 5: four readings held 10 s, two held 60
TABLE = "-A -ww -o pid= -o ppid= -o args="     # the reading of every pane's process tree
BOUND = 120       # a read a loaded host takes long over


@unittest.skipUnless(REAL_TMUX and PS, "no tmux or no ps")
class ScreenHoldsPsByItsCost(unittest.TestCase):
    def test_an_open_screen_reads_a_costly_table_at_most_twice_a_minute(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        Seat(home, "fix-api")
        # a session ak did not start is a seat only while an agent runs in it: the table says
        self.assertEqual(home.tmux("new-session", "-d", "-s", "notes", "sleep 3600").code, 0)
        calls = home.log("ps")
        home.fake("ps", f'#!/bin/sh\necho "$*" >>{shlex.quote(str(calls))}\nsleep {COST}\n'
                        f'exec {shlex.quote(PS)} "$@"\n')
        menu = Terminal(home, "--client", size=(100, 40))
        menu.wait(lambda screen: re.search(r"^[› ] +\d+  fix-api ", screen, re.M), bound=BOUND)
        start, before = time.monotonic(), self.read(calls)
        for _ in range(WATCHED // 5):
            (home.path / ".agentkit/state/runs-moved").touch()
            time.sleep(5)
        # a hold starts each reading HELD from the last, however long a loaded host took over this
        self.assertLessEqual(self.read(calls) - before, 1 + (time.monotonic() - start) // HELD,
                             menu.screen())

    @staticmethod
    def read(calls):
        """How many times the process table was read."""
        return calls.read_text().splitlines().count(TABLE) if calls.exists() else 0


if __name__ == "__main__":
    unittest.main()
