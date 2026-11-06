"""While the pointer is on `Review rounds` on `config · limits`, how your runs ended shows under its
note: `how your N runs ended, since D`, then a bar each ending -- each round up to the last a
run merged in, then `failed` -- its share of N, its count, that share as a whole percent and its
median hours from start to finish.

Counted are the finished runs that are not stopped, from the first that carries changed_lines on:
merged in the round rounds_used names when changed_lines is set, failed when final_state is
`fail`, nothing else.  With none, the chart's place says `no finished runs yet`.

The owner's design of 5 Nov 2026: each limit shows what your runs did.  Black-box: history.db's
`runs` rows written into the Home as any program writes them, then the program `AK_BIN` names
in a person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py, judged by the screen.  The terminal has no colour (NO_COLOR).
This test fails against `/bin/false`.
"""

import calendar
import re
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
HOUR, DAY = 3600, 86400
FIRST = calendar.timegm((2026, 10, 1, 12, 0, 0))     # the first run carrying changed_lines
COLUMNS = ("run_id", "repo", "final_state", "rounds_used", "changed_lines", "started_at",
           "finished_at")
# (final_state, rounds_used, changed_lines, started, hours to finish or None), out of order
COUNTED = [("pass", 2, 40, FIRST + 3 * DAY, 5.0), ("fail", 3, None, FIRST + 4 * DAY, 0.5),
           ("pass", 1, 20, FIRST + 1 * DAY, 1.0), ("pass", 1, 30, FIRST, 2.0),
           ("pass", 3, 90, FIRST + 9 * DAY, 6.3), ("pass", 1, 10, FIRST + 2 * DAY, 3.0),
           ("fail", 3, None, FIRST + 5 * DAY, 0.9), ("pass", 2, 60, FIRST + 6 * DAY, 4.0),
           ("pass", 1, 80, FIRST + 7 * DAY, 1.5), ("pass", 1, 50, FIRST + 8 * DAY, 2.5)]
LEFT_OUT = {"stopped": ("stopped", 1, 40, FIRST + 2 * DAY, 1.0),
            "unfinished": ("running", 2, 30, FIRST + 3 * DAY, None),
            "passed unmerged": ("pass", 1, None, FIRST + 4 * DAY, 2.0),
            "ended in error": ("error", 0, None, FIRST + 5 * DAY, 1.0),
            "failed before the first merge": ("fail", 3, None, FIRST - 6 * DAY, 1.0),
            "passed before the first merge": ("pass", 1, None, FIRST - 11 * DAY, 1.0)}
# (ending, count, percent, median hours) in the order drawn
ENDINGS = [("merged in round 1", 5, 50, "2.0"), ("merged in round 2", 2, 20, "4.5"),
           ("merged in round 3", 1, 10, "6.3"), ("failed", 2, 20, "0.7")]
HEADING = "how your 10 runs ended, since 1 Oct"
BAR = re.compile(r"^  (merged in round \d+|failed) +([━╸─]+)  +(\d+) +(\d+)% +median (\S+) h$")
SHOWN = r"\n  {}\s+[━╸─]+ +{} +{}%"     # an ending's count and share, its bar under it or not


def bars(screen):
    """(ending, bar, count, share, median hours) of each bar line drawn whole."""
    return [found.groups() for line in screen.split("\n") if (found := BAR.match(line.rstrip()))]


def write_runs(home, runs):
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    try:
        connection.execute(f"CREATE TABLE runs ({', '.join(COLUMNS)})")
        connection.executemany(
            f"INSERT INTO runs VALUES ({', '.join('?' * len(COLUMNS))})",
            [(f"202610{number:02d}-1200-fix-api-{number}", "acme", state, rounds, lines, start,
              None if hours is None else start + hours * HOUR)
             for number, (state, rounds, lines, start, hours) in enumerate(runs)])
        connection.commit()
    finally:
        connection.close()


def opened(case, size):
    """`config · limits` from `c`, in a window of its own, the pointer on `Review rounds`."""
    term = Terminal(case.home, size=size, env={"NO_COLOR": "1"})
    case.addCleanup(case.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                    server=SERVER)
    term.wait("esc leave")
    term.keys("c")
    term.wait("r recommended")
    term.keys(*["j"] * 30)       # Limits is the last config row.
    term.wait("› Limits")
    term.keys("Enter")
    term.wait("› Review rounds")
    return term


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RoundsChart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")
        akconfig.write(cls.home, MODELS)
        write_runs(cls.home, [*COUNTED, *LEFT_OUT.values()])

    def test_each_ending_draws_its_bar_count_share_and_median_hours_in_round_order(self):
        shown = opened(self, (100, 40)).wait(
            lambda screen: "failed" in (ending for ending, *_ in bars(screen)))
        drawn = bars(shown)
        self.assertEqual([(ending, int(count), int(share), hours)
                          for ending, _, count, share, hours in drawn], ENDINGS, shown)
        self.assertEqual(len({len(bar) for _, bar, *_ in drawn}), 1, shown)
        for ending, bar, count, *_ in drawn:
            with self.subTest(ending=ending):     # its share of the line full, to half a cell
                self.assertRegex(bar, "^━*╸?─*$")
                full = bar.count("━") + bar.count("╸") / 2
                self.assertLessEqual(abs(full - len(bar) * int(count) / len(COUNTED)), 0.5, bar)

    def test_the_heading_counts_runs_from_the_day_the_first_counted_one_started(self):
        # each run LEFT_OUT, counted, would change N or the day
        self.assertIn(f"\n  {HEADING}\n", opened(self, (100, 40)).wait(HEADING))

    def test_the_chart_is_review_rounds_own(self):
        term = opened(self, (100, 40))
        term.wait(HEADING)
        term.keys("j")
        term.wait("› Max lines per executor task")
        term.wait(lambda screen: HEADING not in screen and "merged in round" not in screen)

    def test_on_40_cells_each_ending_keeps_its_count_and_share(self):
        shown = opened(self, (40, 50)).wait(
            lambda screen: re.search(SHOWN.format("failed", r"\d+", r"\d+"), screen))
        for ending, count, share, _ in ENDINGS:
            with self.subTest(ending=ending):
                self.assertRegex(shown, SHOWN.format(ending, count, share), shown)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NoRuns(unittest.TestCase):
    def test_with_no_counted_run_the_chart_says_none_yet(self):
        for runs in ((), list(LEFT_OUT.values())):
            with self.subTest(runs=len(runs)):
                self.home = Home()
                self.addCleanup(self.home.close)
                fakeadapter.install(self.home, claude="pass", codex="pass")
                akconfig.write(self.home, MODELS)
                if runs:
                    write_runs(self.home, runs)
                opened(self, (100, 40)).wait("no finished runs yet")


if __name__ == "__main__":
    unittest.main()
