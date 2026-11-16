"""An open menu whose reads stopped starts over by itself, and says why in the tick's log.

The owner, 14 Nov 2026: a menu left open showed a seat's old state until it was opened again.  A
read that never lands does that.  In a read every tmux call is bounded (`orch.TMUX_CEILING`) and
every git call too (30 s), but the process table is read by a `ps` with no timeout of its own
(`orch.processes`), which a read runs once ak's tmux server holds a session ak did not start whose
pane the last reading has not seen.  Here that `ps` never answers the open menu -- it sleeps --
and answers it started again: the marker names the open menu's threads, which its exec ends.  A
seat's record changes once a `ps` is stuck; its row shows the change with no key pressed, and the
log says the menu started over and where its threads stood.  On the code before, the row never
changed.

Black-box: ak runs in a terminal of tests/fixtures/akterm.py over a seat of
tests/fixtures/akseat.py.
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
from fixtures.akbin import AK, REAL_TMUX, SYSTEM, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
BOUND = 300       # a read owed is waited out for half a minute at the least, and the menu started
                  # again draws on a host however loaded
# `ps`, which never answers a menu while a thread the marker names is alive in it, and says so
PS = """#!/bin/sh
if [ -f {marker} ]; then
  while read -r thread; do
    if [ -d "/proc/$PPID/task/$thread" ]; then echo "$PPID" >>{hung}; exec sleep 86400; fi
  done <{marker}
fi
exec {real} "$@"
"""


def row(name, word=""):
    """A test of a screen: that seat has a row, reading `word`."""
    return lambda screen: re.search(rf"^[› ] +\d+  {re.escape(name)} .*{word}", screen, re.M)


@unittest.skipUnless(REAL_TMUX and Path("/proc/self/task").exists(), "no tmux, or no /proc")
class ReadsStopped(unittest.TestCase):
    def test_a_menu_whose_reads_stopped_starts_over_and_says_why(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "fable"])
        record = Seat(home, SEAT).record
        marker, hung = home.root / "stuck", home.root / "hung"
        home.fake("ps", PS.format(marker=shlex.quote(str(marker)), hung=shlex.quote(str(hung)),
                                  real=shutil.which("ps", path=os.pathsep.join(SYSTEM))))
        menu = Terminal(home)
        menu.wait(row(SEAT, "Opus"), bound=60)
        pid = program(home, menu)
        marker.write_text("".join(f"{thread}\n" for thread in os.listdir(f"/proc/{pid}/task")
                                  if thread != str(pid)))    # an exec keeps only its first
        done = home.tmux("new-session", "-d", "-s", "scratch", "sleep 86400")
        self.assertEqual(done.code, 0, done.err)
        deadline = time.monotonic() + 60
        while not hung.exists():
            self.assertLess(time.monotonic(), deadline, "no read asked `ps` about the session")
            time.sleep(0.05)
        home.write(f".agentkit/state/session-{SEAT}.json", {**record, "orchestrator": "fable"})
        menu.wait(row(SEAT, "Fable"), bound=BOUND)
        log = (home.path / ".agentkit/tmp/watch.log").read_text()
        self.assertRegex(log, r"menu started over: .*watcher alive.*orch\.py:\d+")


def program(home, menu):
    """The program's own process under the shells its terminal's pane runs."""
    pid = int(home.tmux("display-message", "-p", "-t", menu.pane, "#{pane_pid}",
                        server=SERVER).out)
    while AK not in Path(f"/proc/{pid}/cmdline").read_text().split("\0")[:2]:
        pid = int(Path(f"/proc/{pid}/task/{pid}/children").read_text().split()[0])
    return pid


if __name__ == "__main__":
    unittest.main()
