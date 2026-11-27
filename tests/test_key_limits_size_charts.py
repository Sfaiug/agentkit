"""Under `orchestrator_lines` on `config · limits`, how own pull requests of each size did: once
per change by 25 lines of first review, merged in round 1; bars below the limit, then one from it
up marked `over`, following a limit changed on the page, paged with ↓ on a short terminal, read
from a history from before runs had a kind.  Builds, which `executor_lines` shows by what they
took (tests/test_key_limits_size_table.py), are in no bar.  Black-box, the owner's design of
5 Nov 2026: history.db rows in the Home, `AK_BIN` in a person's terminal
(tests/fixtures/akterm.py), judged by the screen without colour; it fails against `/bin/false`.
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
FIRST = calendar.timegm((2026, 10, 1, 12, 0, 0))
COLUMNS = ("run_id", "repo", "change", "kind", "own_orchestrator", "final_state", "rounds_used",
           "changed_lines", "first_review_lines", "started_at", "finished_at")
# (run, final_state, rounds_used, changed_lines, first_review_lines, started): out of order
BUILDS = [("fix-api-4", "fail", 3, None, 99, FIRST + 3 * DAY),
          ("fix-api-1", "pass", 1, 10, 10, FIRST),
          ("fix-api-2", "pass", 2, 40, 40, FIRST + 1 * DAY),
          ("fix-api-3", "pass", 1, 80, 80, FIRST + 2 * DAY),
          ("fix-api-5", "pass", 1, 100, 100, FIRST + 4 * DAY),
          ("fix-api-6", "pass", 1, 150, 150, FIRST + 5 * DAY),
          ("fix-api-7", "pass", 3, 199, 199, FIRST + 6 * DAY),
          ("fix-api-8", "fail", 3, None, 250, FIRST + 7 * DAY),
          ("fix-api-9", "pass", 1, 300, 300, FIRST + 8 * DAY),     # ran under a higher limit
          ("fix-api-10", "pass", 1, 420, 420, FIRST + 9 * DAY)]
OWN = FIRST + 3 * DAY                  # the first own pull request starts on 4 Oct
# (PR, kind, own_orchestrator, state, rounds_used, changed_lines, first_review_lines, started)
OWN_PRS = [(1, "seat PR", "fable", "fail", 3, None, 10, OWN + 1 * DAY),
           (1, "seat PR", "fable", "pass", 1, 30, 30, OWN + 2 * DAY),    # 25–49, counted once
           (2, "seat PR", "fable", "pass", 1, 5, 5, OWN),
           (3, "seat PR", "fable", "pass", 2, 20, 20, OWN + 3 * DAY),     # merged in round 2
           (8, "seat PR", "fable", "pass", 1, 24, 24, OWN + 4 * DAY),
           (6, None, "astra", "pass", 1, None, 40, OWN + 5 * DAY),       # passed, never merged
           (4, "seat PR", "astra", "pass", 1, 60, 60, OWN + 6 * DAY)]    # ran under a higher limit
# rows neither chart counts, each changing a count or a day if counted: (run_id, change, kind,
# own_orchestrator, final_state, rounds_used, changed_lines, first_review_lines, started, hours)
LEFT_OUT = [("20260920-1200-fix-api-11", "acme/api#9", "PR", None, "pass", 1, 50, 50,
             FIRST - 2 * DAY, 1.0),                             # a review of someone's PR
            ("20260921-1200-review-pr-api-10", "fix-api-12", "PR", None, "pass", 1, 50, 50,
             FIRST - 3 * DAY, 1.0),
            ("20260922-1200-fix-api-13", "fix-api-13", "task", None, "stopped", 1, None, 50,
             FIRST - 4 * DAY, 1.0),
            ("20260923-1200-fix-api-14", "fix-api-14", "task", None, "running", 1, None, 50,
             FIRST - 5 * DAY, None),
            ("20260924-1200-fix-api-15", "fix-api-15", "task", None, "pass", 1, 15, None,
             FIRST - 6 * DAY, 1.0),                             # no first review read
            ("20260925-1200-review-pr-api-5", "acme/api#5", "seat PR", "fable", "pass", 1, 15, None,
             FIRST - 7 * DAY, 1.0),
            ("20260926-1200-review-pr-api-7", "acme/api#7", "seat PR", "fable", "stopped", 1, None,
             15, FIRST - 8 * DAY, 1.0),
            ("20260927-1200-review-pr-api-11", "acme/api#11", "seat PR", "fable", "running", 1, None,
             15, FIRST - 9 * DAY, None)]

ORCHESTRATOR = ("how often an orchestrator's own pull request merged in its first round, "
                "by size · 6 since 4 Oct")
# (bar, passed, count, over) in the order drawn, at each limit
ORCHESTRATOR_50 = [("0–24", 2, 3, False), ("25–49", 1, 2, False), ("50+", 1, 1, True)]
ORCHESTRATOR_100 = [*ORCHESTRATOR_50[:2], ("50–74", 1, 1, False), ("75–99", 0, 0, False),
                    ("100+", 0, 0, True)]
BAR = re.compile(r"^  (\d+–\d+|\d+\+) +([━╸─]+)  +(?:(\d+)%  +)?(\d+)(  over)?$")


def bars(screen):
    """(size, bar, percent or None, count, over) of each bar line drawn whole."""
    return [(size, bar, percent and int(percent), int(count), bool(over))
            for line in screen.split("\n") if (found := BAR.match(line.rstrip()))
            for size, bar, percent, count, over in [found.groups()]]


def drawn(expected):
    """A test of the screen: it draws exactly `expected`'s bars, each its share's whole percent,
    as long as the others and its share of it full, to half a cell."""
    said = [(size, round(100 * passed / count) if count else None, count, over)
            for size, passed, count, over in expected]

    def shows(screen):
        found = bars(screen)
        off = [abs(bar.count("━") + bar.count("╸") / 2 - len(bar) * passed / max(1, count))
               for (_, bar, *_), (_, passed, count, _) in zip(found, expected)]
        return ([(size, *rest) for size, _, *rest in found] == said and max(off, default=0) <= 0.5
                and len({len(bar) for _, bar, *_ in found}) == 1
                and all(re.fullmatch("━*╸?─*", bar) for _, bar, *_ in found))
    return shows


def write_runs(home, columns=COLUMNS):
    rows = [(f"202610{number + 1:02d}-1200-{run}", "acme", run, "task", None, state, rounds,
             changed, lines, start, start + HOUR)
            for number, (run, state, rounds, changed, lines, start) in enumerate(BUILDS)]
    rows += [(f"202610{number + 1:02d}-1200-review-pr-api-{pr}-{number}", "acme", f"acme/api#{pr}",
              kind, own, state, rounds, changed, lines, start, start + HOUR)
             for number, (pr, kind, own, state, rounds, changed, lines, start) in enumerate(OWN_PRS)]
    rows += [(run_id, "acme", *rest, start, None if hours is None else start + hours * HOUR)
             for run_id, *rest, start, hours in LEFT_OUT]
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    try:
        connection.execute(f"CREATE TABLE runs ({', '.join(map(repr, columns))})")
        connection.executemany(f"INSERT INTO runs VALUES ({', '.join('?' * len(columns))})",
                               [[value for column, value in zip(COLUMNS, row) if column in columns]
                                for row in rows])
        connection.commit()
    finally:
        connection.close()


def made_home(cleanup, columns=COLUMNS):
    home = Home()
    cleanup(home.close)
    fakeadapter.install(home, claude="pass", codex="pass")
    akconfig.write(home, MODELS)
    write_runs(home, columns)
    return home


def opened(case, home, row, size=(100, 40)):
    """`config · limits` from `c`, in a window of its own, the pointer on `row`."""
    term = Terminal(home, size=size, env={"NO_COLOR": "1"})
    case.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                    server=SERVER)
    term.wait("esc leave")
    term.keys("c")
    term.wait("r recommended")
    term.keys(*["j"] * 7)     # Limits is the eighth row, the two models first.
    term.wait("› Limits")
    term.keys("Enter")
    term.wait("› Review rounds")
    term.keys(*["j"] * {"Max lines per executor task": 1, "Max lines per orchestrator task": 2,
                        "Findings that end a run for rescoping": 4}[row])
    term.wait(f"› {row}")
    return term


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SizeCharts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = made_home(cls.addClassCleanup)

    def test_orchestrator_bars_own_pull_requests_once_each_by_their_largest_first_review(self):
        # counted per run, or sized by its first run, #1 would add to 0–24; a build counted would
        # add to the count and move the day
        shown = opened(self, self.home, "Max lines per orchestrator task").wait(
            drawn(ORCHESTRATOR_50))
        self.assertIn(f"\n  {ORCHESTRATOR}\n", shown)

    def test_on_a_short_terminal_down_and_up_turn_the_chart_pages_before_leaving_the_row(self):
        term = opened(self, self.home, "Max lines per orchestrator task")
        term.resize(100, 15)          # the rows and the heading, the bars a page on
        first = lambda screen: ("› Max lines per orchestrator task" in screen
                                and ORCHESTRATOR in screen and not bars(screen))
        term.wait(first)
        term.keys("j")
        term.wait(drawn(ORCHESTRATOR_50))
        term.keys("k")
        term.wait(first)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ChangedLimit(unittest.TestCase):
    def test_the_bars_follow_a_new_limit_on_a_history_from_before_runs_had_a_kind(self):
        home = made_home(self.addCleanup, [column for column in COLUMNS if column != "kind"])
        term = opened(self, home, "Max lines per orchestrator task")
        term.wait(drawn(ORCHESTRATOR_50))
        term.keys("Right", "Right")   # two steps up: 50 to 100
        term.wait(drawn(ORCHESTRATOR_100))


if __name__ == "__main__":
    unittest.main()
