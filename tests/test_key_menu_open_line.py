"""The line a highlighted row opens: who builds and who reviews, whatever its word.

The owner reads a seat's state from its row and opens the one line under it with the
highlight (the screen approved on 14 Oct 2026).  Every seat, a done one too, never saying what
it got done (the owner, 9 Nov 2026), names each role and the models in it, and never a task's
squares: its row counts its tasks in flight (the owner, 17 Nov 2026), and a run that ended is no
task in flight.  Black-box:
the program `AK_BIN` names runs in a person's terminal (tests/fixtures/akterm.py), of eight
colours so nothing breathes, beside tests/fixtures/akseat.py's seats and run records like those
`ak run` writes, and this test fails against `/bin/false`.
"""

import re
import subprocess
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

OPENS = 60      # the first draw looks at every seat, which a loaded host makes slow
UNDER = " " * 5     # an open line starts under the row's name
COLOURS = re.compile(r"\x1b\[[0-9;]*m")
LIVE = Path("/proc/sys/kernel/random/boot_id")


def done_line(what):
    return f"- [x] {what} · check: `true` · acme · written 2026-10-02 12:40 · done abc1234"


def alive(pid):
    """A run record's say that its loop is process `pid`, as `ak run` fingerprints it."""
    ticks = int(Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19])
    return {"pid": pid, "started_at": time.time(),
            "process_identity": {"boot": LIVE.read_text().strip(), "ticks": ticks}}


def opened(screen, name):
    """The row of `name` while highlighted and the line under it, or None."""
    lines = [line.rstrip() for line in COLOURS.sub("", screen).splitlines()] + [""]
    at = next((n for n, line in enumerate(lines) if re.match(rf"› \d+  {name} ", line)), None)
    return None if at is None else (lines[at], lines[at + 1])


def opens(name):
    """A test of a screen: the highlight is on `name` and its line is open."""
    return lambda screen: (opened(screen, name) or ("", ""))[1].startswith(UNDER)


# The row the owner points at (pointer or ↑/↓) opens one line under it: who builds and who
# reviews, and no task's squares. [2, 14, 19, 23, 26 Oct, 9, 17 Nov 2026]
@unittest.skipUnless(REAL_TMUX and LIVE.exists(), "no tmux, or no /proc to fingerprint a run")
class OpenLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "spark", "fable"])
        loop = subprocess.Popen(["sleep", "600"])
        cls.addClassCleanup(loop.wait)
        cls.addClassCleanup(loop.kill)
        made = int(time.time()) - 900
        for at, (name, screen, crew) in enumerate((
                ("beta", "claude-prompt-pane.txt", {}),
                ("fix-api", "claude-working-pane.txt", {"workers": ["spark"],
                                                        "reviewers": ["opus"]}),
                ("gamma", "claude-prompt-pane.txt", {"orchestrator": "fable",
                                                     "workers": ["spark", "fable"],
                                                     "reviewers": ["fable"]}))):
            Seat(home, name, screen=screen, record={"created": made + 60 * at, **crew})
        home.write(".agentkit/state/plan-beta.md", "# beta\n" + done_line("tidy the readme")
                   + "\n" + done_line("the parser is shipped") + "\n")
        for run, state in (("0900-aaaa", {"state": "running", "step": "reviewer",
                                          **alive(loop.pid)}),
                           ("0901-bbbb", {"state": "running", "step": "executor",
                                          **alive(loop.pid)}),
                           ("0902-cccc", {"state": "waiting", "waiting_on": {"line": "acme"}}),
                           ("0903-dddd", {"state": "queued", **alive(loop.pid)}),
                           ("0904-eeee", {"state": "pass", "step": "merge"})):
            home.write(f".agentkit/runs/20261020-{run}/run.json",
                       {**state, "launched_session": "fix-api"})
        menu = Terminal(home, size=(100, 30), env={"TERM": "xterm"})
        cls.addClassCleanup(menu.exit_code)
        cls.addClassCleanup(menu.keys, "Escape")
        menu.wait(lambda screen: all(word in screen for word in ("✓ done", "● working",
                                                                 "○ idle")), bound=OPENS)
        cls.screens = {}
        # the first row's line opens only once the highlight has moved
        for key, name in (("j", "fix-api"), ("j", "gamma"), ("k", "fix-api"), ("k", "beta")):
            menu.keys(key)
            cls.screens[name] = opened(menu.wait(opens(name)), name)

    def test_a_done_seat_opens_who_builds_and_reviews_never_what_got_done(self):
        row, line = self.screens["beta"]
        self.assertRegex(row, r"✓ done +━+ 2 of 2$")
        self.assertEqual(line, f"{UNDER}build and review: Opus 5.5 xhigh")

    def test_a_working_seat_opens_who_builds_and_who_reviews_never_its_tasks(self):
        row, line = self.screens["fix-api"]
        # building, waiting its turn, in review and in the landing line; the one that passed
        # ended
        self.assertRegex(row, r"● working +─+ no plan yet · 4 tasks$")
        self.assertEqual(line, f"{UNDER}build: Spark 1.3 Contributor xhigh   review: Opus 5.5 "
                               "xhigh")

    def test_a_seat_at_rest_opens_each_role_with_the_models_in_it(self):
        row, line = self.screens["gamma"]
        self.assertTrue(row.endswith("○ idle"), row)
        self.assertEqual(line, f"{UNDER}build: Spark 1.3 Contributor xhigh, Fable 5.1 xhigh   "
                               "review: Fable 5.1 xhigh")


if __name__ == "__main__":
    unittest.main()
