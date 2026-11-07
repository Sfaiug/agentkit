"""Under each limit on `config · limits`, a few plain sentences say what your runs would have
done at the value in force, said again as ← and → move it.  M is the last round a counted run
merged in, F the number that failed (the runs tests/test_key_limits_rounds_chart.py counts).

`Review rounds` at 0 says review is off and no run went that way; under M, the changes merged
after that round and the F failed would have gone back to their orchestrator; at M, F went
back; at M + 1, a guess that it would go as round M did, those merged in M over those and F;
further, the runs can't say.

The line limits read the first reviews of runs that ended passed, failed or blocked, not
stopped: their size, whether an orchestrator's own pull request or a build, and whether it
passed in round 1, for a build, or merged in round 1, for an own pull request -- a pass that
merged nothing (--no-merge) passed and did not merge.  At a value between 0 and the largest,
those of that many lines or more, as the size bars split them, would have been split, or made
tasks, with how often their first round went so and how often the rest's did; at 0 executors or
orchestrators build nothing; past the largest, no run can say.

The owner's design of 5 Nov 2026.  Black-box: history.db's `runs` rows written into the Home as
any program writes them, then the program `AK_BIN` names in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, judged by
the screen.  The terminal has no colour (NO_COLOR).  This test fails against `/bin/false`.
"""

import calendar
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}
START = calendar.timegm((2026, 10, 1, 12, 0, 0))
COLUMNS = ("run_id", "repo", "final_state", "rounds_used", "changed_lines", "first_review_lines",
           "own_orchestrator", "started_at", "finished_at")
# the round each merged in, then F's first review sizes: builds, then own pull requests; a size
# at a step pins that it counts with those of that many lines or more
BUILDS = {1: (40, 90, 120, 180, 220, 350), 2: (150, 260, 310), 3: (300, 450, 190),
          None: (330, 410, 240, 60)}
OWN = {1: (25, 30, 50, 70), 2: (60, 90), None: (20, 55, 120)}
# passed in round 1 and merged nothing, as a --no-merge run does: a build's first review passed,
# an own pull request's round 1 merged nothing, and neither is in the rounds chart
UNMERGED = {None: 200, "fable": 40}
# (final_state, rounds_used, first_review_lines, own): none counted, each would move a number
LEFT_OUT = [("stopped", 1, 900, None), ("running", 2, 700, None), ("error", 1, 800, None),
            ("stopped", 1, 300, "fable")]
# 25 runs: merged in round 1 10, round 2 5, round 3 3 (M), and 7 failed (F)
ROUNDS = {
    0: "Off: no reviewer, so a change lands when its checks pass. None of your runs went that "
       "way, so they can't say how it would go.",
    1: "The 8 changes that merged after round 1 would have gone back to their orchestrator "
       "instead, and the 7 that failed would have gone back after round 1.",
    2: "The 3 changes that merged after round 2 would have gone back to their orchestrator "
       "instead, and the 7 that failed would have gone back after round 2.",
    3: "7 changes (28%) went back to their orchestrator after 3 rounds.",
    # 3 of 3 + 7 merged in round 3: 30%, and 30% of 7 is 2.1
    4: "If a 4th round went like the 3rd, where 30% merged, about 2 of those 7 would have "
       "merged. No run has had one, so this is a guess.",
    5: "No run has gone past 3 rounds, so your runs can't say."}
# 17 builds, the largest 450 lines
EXECUTOR = {
    300: "6 of your 17 builds (35%) were 300 lines or more and would have been split. Their "
         "first review passed 17% of the time, and 55% below 300 lines.",
    200: "10 of your 17 builds (59%) were 200 lines or more and would have been split. Their "
         "first review passed 30% of the time, and 57% below 200 lines.",
    0: "Off: executors build nothing, so your runs can't say how that would go.",
    500: "Your largest build was 450 lines, so your runs can't say how bigger ones would go.",
    "no limit": "Your largest build was 450 lines, so your runs can't say how bigger ones would "
                "go."}
# 10 own pull requests
ORCHESTRATOR = {
    50: "6 of your orchestrators' 10 own pull requests were 50 lines or more and would have "
        "been tasks. Round 1 merged 33% of them, and 50% below 50 lines.",
    25: "9 of your orchestrators' 10 own pull requests were 25 lines or more and would have "
        "been tasks. Round 1 merged 44% of them, and 0% below 25 lines.",
    0: "Off: orchestrators build nothing themselves, so every one of their 10 own pull "
       "requests would have been a task."}
NAMES = {"Review rounds": 3, "Max lines per executor task": 300,
         "Max lines per orchestrator task": 50}


def counted():
    """(final_state, rounds_used, changed_lines, first_review_lines, own) of each counted run."""
    return [("fail" if ending is None else "pass", ending or 3, None if ending is None else size,
             size, own)
            for own, made in ((None, BUILDS), ("fable", OWN))
            for ending, sizes in made.items() for size in sizes]


def write_runs(home):
    rows = [*counted(), *(("pass", 1, None, size, own) for own, size in UNMERGED.items()),
            *((state, rounds, None, size, own) for state, rounds, size, own in LEFT_OUT)]
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    try:
        connection.execute(f"CREATE TABLE runs ({', '.join(COLUMNS)})")
        connection.executemany(
            f"INSERT INTO runs VALUES ({', '.join('?' * len(COLUMNS))})",
            [(f"20261001-1200-fix-api-{number}", "acme", state, rounds, lines, size, own,
              START + number * 3600, None if state == "running" else START + number * 3600 + 600)
             for number, (state, rounds, lines, size, own) in enumerate(rows)])
        connection.commit()
    finally:
        connection.close()


def pointed(screen, name):
    """The value `name`'s row shows while it is pointed, its arrows aside, then what follows."""
    return next((" ".join(word for word in line[2 + len(name):].split()
                          if word not in ("◂", "▸"))
                 for line in screen.split("\n") if line.startswith(f"› {name}")), "")


def said(screen):
    """The screen's words, a space apart, so a sentence wrapped over lines reads whole."""
    return " ".join(screen.split())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhatIf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")
        write_runs(cls.home)

    def walk(self, name, path):
        """`config · limits` from `c` over ak's defaults, the pointer moved onto `name`, then
        each (arrows, value, sentence) of `path`: once `name` shows `value`, the sentence is
        under it."""
        akconfig.write(self.home, MODELS)
        self.addCleanup(akconfig.write, self.home, MODELS)      # ← → save a value
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys(*["j"] * 30)       # Limits is the last config row.
        term.wait("› Limits")
        term.keys("Enter")
        term.wait("› Review rounds")
        term.keys(*["j"] * list(NAMES).index(name))
        for arrows, value, sentence in path:
            with self.subTest(name=name, value=value):
                if arrows:
                    term.keys(*arrows)
                term.wait(lambda screen: f"{pointed(screen, name)} ".startswith(
                    f"{'off' if value == 0 else value} ") and sentence in said(screen))

    def test_review_rounds_at_0_under_m_at_m_one_past_and_further(self):
        self.walk("Review rounds", [((), 3, ROUNDS[3]), (("Left",), 2, ROUNDS[2]),
                                    (("Left",), 1, ROUNDS[1]), (("Left",), 0, ROUNDS[0]),
                                    (("Right",) * 4, 4, ROUNDS[4]), (("Right",), 5, ROUNDS[5])])

    def test_executor_lines_between_0_and_the_largest_at_0_and_past_it(self):
        self.walk("Max lines per executor task", [
            ((), 300, EXECUTOR[300]), (("Left",), 200, EXECUTOR[200]),
            (("Left",) * 2, 0, EXECUTOR[0]), (("Right",) * 5, 500, EXECUTOR[500]),
            (("Right",) * 6, "no limit", EXECUTOR["no limit"])])

    def test_orchestrator_lines_between_0_and_the_largest_and_at_0(self):
        self.walk("Max lines per orchestrator task", [
            ((), 50, ORCHESTRATOR[50]), (("Left",), 25, ORCHESTRATOR[25]),
            (("Left",), 0, ORCHESTRATOR[0])])


if __name__ == "__main__":
    unittest.main()
