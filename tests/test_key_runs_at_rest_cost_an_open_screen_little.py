"""What a run at rest costs an open screen barely depends on how many there are, and a row still
tells of one that moved.

Every read of an open screen stat'ed every run ak ever ran and resolved its paths, 0.05 of a core
over 5,126 runs of which 40 could still change.  The cost is the screen's own system time, what
this removes: it separates reading every run from reading the open ones by 4x, where total CPU
does by 2x and host load moves it more.  Its yardstick is the same look done plainly in this
test's process, so a slow host raises both.
An open run's paths are resolved again only once its record changed or at a full read, so a symlink
that moved shows by then.
Black-box, on tests/test_key_idle_screen_reads_only_what_changed.py's open screen.
"""

import json
import os
from pathlib import Path
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_idle_screen_reads_only_what_changed import (BOUND, MINUTE, SEATS, OpenScreen, ended,
                                                          row)

RUNS = 6000
OWN = 100         # runs naming each listed seat, the rest a hundred past seats with no record:
                  # on a host's screen one owns about 55, and half of all runs belong to none
WEEK = 7 * 86400
WINDOW = 20       # seconds of one window of CPU while a screen with no runs settles
LOOKS = 5         # what the runs may add, in plain looks at every run: reading them all on every
                  # read adds about 9 and reading the open ones about 2
LATE = 300        # five times what a full read may lag, for a loaded host


def going(record):
    """That record of a run going."""
    return {**record, "state": "running", "verdict": None, "merged": False, "step": "executor",
            "started_at": time.time(), "finished_at": None}


class RunsAtRestCostAnOpenScreenLittle(OpenScreen):
    """A screen over three seats, measured with no runs and left with the 6,000 read."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home(tmux_log=False)
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        repo, now = home.path / "code" / "acme", int(time.time())
        for n, name in enumerate(SEATS[:3]):      # the first gone from tmux
            Seat(home, name, cwd=repo, alive=n != 0, record={"created": now - 7200 + n})
        cls.menu = Terminal(home, "--client", size=(100, 60))
        cls.menu.wait(row(SEATS[2]), bound=BOUND)
        cls.pid = cls.screen_pid()
        cls.steady()
        cls.bare = cls.still_minute()
        cls.runs, cls.files = {}, []
        for n in range(RUNS):                     # as a home keeps them
            seat = SEATS[n // OWN] if n < 3 * OWN else f"past-{n % 100:02}"
            record = ended(n, seat, now)
            task = home.write(f".agentkit/runs/{record['run_id']}/task.md", "Fix it.\n", ago=WEEK)
            kept = home.write(task.with_name("run.json"),
                              {**record, "task": str(task), "repo": str(repo)}, ago=WEEK)
            cls.runs[seat] = kept
            cls.files.append((kept, task, repo))
        cls.quiet(cls.held())

    @classmethod
    def steady(cls):
        """Once two windows of the screen's CPU are within a fifth of each other: done with its
        opening, where `quiet`'s budget, what the files hold, is too small to tell."""
        deadline, last = time.monotonic() + BOUND, None
        while True:
            assert time.monotonic() < deadline, "the screen never settled"
            start = cls.cpu()
            time.sleep(WINDOW)
            window = cls.cpu() - start
            if last is not None and abs(window - last) * 5 <= max(window, last):
                return
            last = window

    @classmethod
    def still_minute(cls):
        """The lower of two still minutes of the screen's own system time, in clock ticks,
        without its children, which are its tmux calls and not its runs."""
        def stime():
            return int(Path(f"/proc/{cls.pid}/stat").read_text().rpartition(")")[2].split()[12])

        minutes = []
        for _ in range(2):
            start = stime()
            time.sleep(MINUTE)
            minutes.append(stime() - start)
        return min(minutes)

    def plain_look(self):
        """Clock ticks of this process's system time looking once at every run, as a read did."""
        start = os.times().system
        for kept, task, repo in self.files:
            os.stat(kept)
            os.path.realpath(task)
            os.path.realpath(repo)
        return (os.times().system - start) * os.sysconf("SC_CLK_TCK")

    def test_1_the_runs_add_less_than_a_few_plain_looks_a_minute(self):
        added = self.still_minute() - self.bare
        look = sum(self.plain_look() for _ in range(5)) / 5
        self.assertLess(added, LOOKS * look, f"the runs add {added} ticks, a plain look is {look}")

    def test_2_a_run_at_rest_that_changes_still_shows(self):
        for seat in SEATS[:2]:                    # past no mark: the run's writer told nobody
            self.home.write(self.runs[seat], going(json.loads(self.runs[seat].read_text())))
        for seat in SEATS[:2]:
            self.menu.wait(row(seat, "● working"), bound=LATE)

    def test_3_a_new_run_shows_at_once_and_goes_with_its_directory(self):
        record = going(ended(RUNS, SEATS[2], time.time()))
        kept = self.home.write(f".agentkit/runs/{record['run_id']}/run.json", record)
        (self.home.path / ".agentkit/state/runs-moved").touch()
        self.menu.wait(row(SEATS[2], "● working"))
        shutil.rmtree(kept.parent)
        self.menu.wait(self.not_working)

    def not_working(self, screen):
        return row(SEATS[2])(screen) and not row(SEATS[2], "● working")(screen)

    def test_4_a_symlink_that_moved_shows_by_a_full_read_and_a_changed_record_at_once(self):
        code, sandbox = self.home.path / "code", self.home.path / ".agentkit/tmp/smoke-acme"
        link = code / "acme-link"
        sandbox.mkdir(parents=True)
        link.symlink_to(code / "acme")
        record = {**going(ended(RUNS + 1, SEATS[2], time.time())), "repo": str(link)}
        kept = self.home.write(f".agentkit/runs/{record['run_id']}/run.json", record)
        moved = self.home.path / ".agentkit/state/runs-moved"
        moved.touch()
        self.menu.wait(row(SEATS[2], "● working"))
        link.unlink()                             # now the suite's own run, which no screen counts
        link.symlink_to(sandbox)
        self.menu.wait(self.not_working, bound=LATE)
        self.home.write(kept, {**record, "repo": str(code / "acme")})
        moved.touch()
        self.menu.wait(row(SEATS[2], "● working"))


if __name__ == "__main__":
    unittest.main()
