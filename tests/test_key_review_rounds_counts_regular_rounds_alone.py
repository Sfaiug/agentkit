"""On `config · limits`, what `Review rounds` says its runs would have done counts the runs that
used no round past their own `review_rounds`: one that merged or failed in an extra round with
one finding left (tests/test_key_one_finding_left_gets_extra_rounds.py) is not said under it,
though its table shows its task over the rounds held (tests/test_key_limits_rounds_table.py).
A run's row in history.db keeps, as it finishes, its rounds past the `review_rounds` its record
kept, empty for none; a row an older agentkit wrote, that column empty, or one in a history
nothing may write, without it, is counted as it always was.

Black-box, built as tests/test_key_limits_what_if.py is: history.db's `runs` rows written into
the Home as any program writes them, then the program `AK_BIN` names in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, judged by
the screen; and a run of that program, scripted as
tests/test_key_one_finding_left_gets_extra_rounds.py scripts it, judged by its row and the
screen.  The terminal has no colour (NO_COLOR).  This test fails against `/bin/false`.
"""

import calendar
import contextlib
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_one_finding_left_gets_extra_rounds import DISPUTE, FIX, ONE, WORK

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}
START = calendar.timegm((2026, 10, 1, 12, 0, 0))
COLUMNS = ("run_id", "repo", "final_state", "rounds_used", "changed_lines", "started_at",
           "finished_at")
# (final_state, rounds_used, changed_lines, rounds past 3), in start order: three merged in
# round 1, two in round 2, one in round 3 and two failed after it; then one merged in its 4th
# round and one failed after its 5th
RUNS = [*[("pass", 1, 40, None)] * 3, *[("pass", 2, 60, None)] * 2, ("pass", 3, 80, None),
        *[("fail", 3, None, None)] * 2, ("pass", 4, 90, 1), ("fail", 5, None, 2)]
# `Review rounds` over RUNS at ak's 3: its sentence, and whether it counts the two past round 3
REGULAR = ("2 changes (25%) went back to their orchestrator after 3 rounds.", False)
# the same rows, their rounds past 3 empty: as today
TODAY = ("The 1 change that merged after round 3 would have gone back to their orchestrator "
         "instead, and the 3 that failed would have gone back after round 3.", True)
# its table's head and the row of a task that went 4 rounds, its words a space apart (`said`)
OVER = "rounds tasks went live time usage 4 1 over"
# The Home's notify sink marks every run a test suite's, which ak never records
OWNERS = {"AK_NOTIFY_SINK": None}


def write_runs(home, kept, writable=True):
    """RUNS, an hour apart, into `home`'s history.db in the journal mode ak writes: each with
    its rounds past 3 where `kept`, else empty; where not `writable`, without that column, in a
    history nothing may write, so nothing adds it."""
    columns = (*COLUMNS, *["extra_rounds_used"] * writable)
    db = home.path / ".agentkit/history.db"
    with contextlib.closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"CREATE TABLE runs ({', '.join(columns)})")
        connection.executemany(
            f"INSERT INTO runs VALUES ({', '.join('?' * len(columns))})",
            [(f"20261001-1200-fix-api-{number}", "acme", state, rounds, lines,
              START + number * 3600, START + number * 3600 + 600, extra if kept else None
              )[:len(columns)]
             for number, (state, rounds, lines, extra) in enumerate(RUNS)])
    if not writable:
        db.chmod(0o444)


def said(screen):
    """The screen's words, a space apart, so a sentence wrapped over lines reads whole."""
    return " ".join(screen.split())


def review_rounds(test, home, words):
    """`config · limits` from `c` over ak's defaults, `Review rounds` pointed: the screen once
    `words` are under it, its words a space apart."""
    term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
    test.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                    server=SERVER)
    term.wait("esc leave")
    term.keys("c")
    term.wait("r recommended")
    term.keys(*["j"] * 7)     # Limits is the eighth row, the two models first.
    term.wait("› Limits")
    term.keys("Enter")
    return said(term.wait(lambda screen: "› Review rounds" in screen
                          and words in said(screen)))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ReviewRounds(unittest.TestCase):
    def reads(self, says, kept=False, writable=True):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        write_runs(home, kept, writable)
        akconfig.write(home, MODELS)
        sentence, past = says
        shown = review_rounds(self, home, sentence)
        self.assertEqual("would have gone back after round 3" in shown, past, shown)

    def test_a_run_past_its_review_rounds_is_not_counted(self):
        self.reads(REGULAR, kept=True)

    def test_with_its_rounds_past_them_empty_each_is_counted_as_today(self):
        self.reads(TODAY)

    def test_a_history_nothing_may_write_counts_each_as_today(self):
        self.reads(TODAY, writable=False)


class ARunThatMergedInItsFourthRound(unittest.TestCase):
    """Three reviews each left one finding, and the fourth passed: the change merged."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        GitHub(cls.home).grant(rig.slug, "WRITE")       # a run that passed could push and merge
        akconfig.write(cls.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakeadapter.install(cls.home, claude=[WORK, DISPUTE, DISPUTE, FIX],
                            codex=[ONE, ONE, ONE, "pass"])
        task = taskfile.write(cls.home, rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), env=OWNERS, timeout=600)
        cls.run_id = taskfile.only_run(cls.home).name

    def test_its_row_keeps_one_round_past_its_review_rounds(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        with contextlib.closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db:
            row = db.execute("SELECT final_state, rounds_used, extra_rounds_used FROM runs "
                             "WHERE run_id=?", (self.run_id,)).fetchone()
        self.assertEqual(row, ("pass", 4, 1))

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_its_task_shows_over_the_rounds_held_and_is_not_said_under_them(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertNotIn("would have gone back", review_rounds(self, self.home, OVER))


if __name__ == "__main__":
    unittest.main()
