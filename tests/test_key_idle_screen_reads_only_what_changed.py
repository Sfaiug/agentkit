"""An idle ak screen reads only what changed: over a minute with nothing changing it reads less
than its seats' and runs' files hold, and a seat or run file changed under it shows at its next
refresh.

Each refresh used to parse every seat's record again for every seat and for every run, and
read every plan once for each of the four places that look at it, some forty megabytes a minute
over thirty seats and 2,000 runs, a quarter of a core for as long as a screen stayed open.
What the screen reads is its own `rchar` (/proc/<pid>/io), its tmux calls' included, so tmux
runs unlogged.  Black-box: the program `AK_BIN` names runs in a person's terminal
(tests/fixtures/akterm.py) beside tests/fixtures/akseat.py's seats.
"""

import json
import os
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akseat import PLAN_LINE, Seat
from fixtures.akterm import SERVER, Terminal

SEATS = [f"acme-{n:02}" for n in range(30)]
RUNS = 2000
MINUTE = 60
QUIET = 10        # seconds read at the pace of less than the budget a minute: its opening is done
BOUND = 600       # its opening upkeep reaps every run, which a loaded host makes slow
SAID = " ".join(["The review found nothing left to fix in this round."] * 25)
# a plan as one lies about after a week: what its seat got done, then the line still open
PLAN = "".join(f"- [x] Fix {n} of acme is in · check: `python3 tests/test_acme_{n}.py` · acme · "
               f"written 2026-10-20 09:00 on 0123456789ab · done 89abcdef0123 Fix {n} (#{n})\n"
               for n in range(100)) + PLAN_LINE + "\n"


def ended(n, seat, now):
    """An ended run's record as it lies about after a week: merged, handed back, its tree swept,
    its rounds summed up."""
    return {"run_id": f"20261022-{n:04}-fix-{n}", "title": f"fix {n}", "launched_session": seat,
            "state": "pass", "verdict": "PASS", "merged": True, "step": "merge",
            "branch": f"ak/fix-{n}", "started_at": now - 7 * 86400 - n,
            "finished_at": now - 7 * 86400 - n + 900, "handed_back": now - 7 * 86400,
            "reported": True, "tree_stopped": [None, None], "round_summaries": [SAID] * 6}


def row(name, word=""):
    """A test of a screen: that seat has a row, reading `word`."""
    return lambda screen: re.search(rf"^[› ] +\d+  {re.escape(name)} .*{word}", screen, re.M)


@unittest.skipUnless(REAL_TMUX and Path("/proc/self/io").exists(), "no tmux, or no /proc io")
class IdleScreenReadsOnlyWhatChanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home(tmux_log=False)
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        now = int(time.time())
        for n, name in enumerate(SEATS):      # a third gone from tmux, every other one planned
            Seat(home, name, cwd=home.path / "code" / "acme", alive=n % 3 != 0,
                 record={"created": now - 7200 + n})
            if n % 2 == 0:
                home.write(f".agentkit/state/plan-{name}.md", PLAN)
        cls.runs = {}
        for n in range(RUNS):
            record = ended(n, SEATS[n % len(SEATS)], now)
            cls.runs[record["launched_session"]] = home.write(
                f".agentkit/runs/{record['run_id']}/run.json", record)
        cls.menu = Terminal(home, "--client", size=(100, 60))
        cls.menu.wait(row(SEATS[-1]), bound=BOUND)
        cls.pid, cls.budget = cls.screen_pid(), cls.held()
        paces, deadline = [cls.read()], time.monotonic() + BOUND
        while len(paces) <= QUIET or paces[-1] - paces[-1 - QUIET] >= cls.budget * QUIET / MINUTE:
            assert time.monotonic() < deadline, "the screen never went quiet"
            time.sleep(1)
            paces.append(cls.read())

    @classmethod
    def screen_pid(cls):
        """The program's own process under the shells its terminal's pane runs: the one started
        as the program, or by the interpreter its first line names."""
        pid = int(cls.home.tmux("display-message", "-p", "-t", cls.menu.pane, "#{pane_pid}",
                                server=SERVER).out)
        while AK not in Path(f"/proc/{pid}/cmdline").read_text().split("\0")[:2]:
            pid = int(Path(f"/proc/{pid}/task/{pid}/children").read_text().split()[0])
        return pid

    @classmethod
    def read(cls):
        """Bytes the screen has read so far, its children's once it reaped them."""
        io = Path(f"/proc/{cls.pid}/io").read_text()
        return int(re.search(r"^rchar: (\d+)$", io, re.M)[1])

    @classmethod
    def held(cls):
        """Bytes every seat's files and every run's hold."""
        seat = re.compile(rf".+-(?:{'|'.join(SEATS)})\.\w+$")
        state, runs = cls.home.path / ".agentkit/state", cls.home.path / ".agentkit/runs"
        return (sum(path.stat().st_size for path in state.iterdir() if seat.match(path.name))
                + sum(path.stat().st_size for path in runs.rglob("*") if path.is_file()))

    def test_1_an_idle_minute_reads_less_than_the_files_hold(self):
        start = self.read()
        time.sleep(MINUTE)
        self.assertLess(self.read() - start, self.budget)

    def going(self, run, record):
        """That run going, touching the mark every open screen reads again on, as a run's every
        move does (`handback.redress_seat`)."""
        self.home.write(run, {**record, "state": "running", "verdict": None, "merged": False,
                              "step": "executor", "started_at": time.time(), "finished_at": None})
        (self.home.path / ".agentkit/state/runs-moved").touch()

    def test_2_a_changed_seat_or_run_file_shows_at_the_next_refresh(self):
        # a seat tmux lost no longer holds a conversation to resume: it has no row to reopen
        gone = self.home.path / ".agentkit/state/session-acme-09.json"
        record = json.loads(gone.read_text())
        del record["conversation"]
        self.home.write(gone, record)
        run = self.runs["acme-03"]
        self.going(run, json.loads(run.read_text()))
        # A screen reads one refresh at a time.  A new run of acme-15's goes after the changes,
        # so the refresh drawing it ended after they landed; acme-21's goes once that is drawn,
        # so the refresh drawing it began after them, and shows them both however soon it came.
        for n, witness in enumerate(("acme-15", "acme-21"), RUNS):
            record = ended(n, witness, time.time())
            self.going(self.home.path / f".agentkit/runs/{record['run_id']}/run.json", record)
            screen = self.menu.wait(row(witness, "● working"))
        self.assertIsNone(row("acme-09")(screen))
        self.assertTrue(row("acme-03", "● working")(screen))


if __name__ == "__main__":
    unittest.main()
