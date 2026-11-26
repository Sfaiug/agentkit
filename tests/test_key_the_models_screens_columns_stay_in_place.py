"""The `c` screen's three role columns stand in the same place whatever is marked, at whatever
effort (the owner, 26 Nov 2026), sized by the listed models' catalog levels alone; on a narrow
terminal the bars give way, then the roles fold under each whole model name.  Black-box: `AK_BIN`
as the popup over akseat.py seats in an akterm.py terminal."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

MODELS = {"opus": {"effort": "low", "exec_effort": "high"},
          "haiku": {"harness": "claude", "model": "claude-haiku-4-5", "effort": "none"}}
FULL = {"orchestrator": "opus", "workers": ["opus", "haiku"], "reviewers": ["opus", "haiku"],
        "efforts": {"opus": {"effort": "medium", "exec_effort": "low"}}}
BARE = {"orchestrator": "haiku", "workers": [], "reviewers": ["haiku"]}  # no builder, one effort


def heads(screen):
    return next(line for line in screen.splitlines() if line.split() == ["orch", "builds", "reviews"])


def role_starts(screen):
    """Where each folded role's head and mark stand on Opus's lines, 1-based."""
    shown = screen.splitlines()
    at = next(index for index, line in enumerate(shown) if "Opus 5.5" in line)
    return tuple((shown[at + n].index(head) + 1,
                  next(col for col, ch in enumerate(shown[at + n], 1) if ch in "●○■□"))
                 for n, head in enumerate(("orch", "builds", "reviews"), 1))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ColumnsStayInPlace(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, MODELS, orchestrator="opus", workers=["opus"], reviewers=["opus"])
        fakeadapter.install(self.home, claude="pass")

    def open_c(self, seat, record, columns, home=None):
        home = home or self.home
        Seat(home, seat, record=record)
        term = Terminal(home, "attach", "--overlay", size=(columns, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": seat})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        screen = term.wait(lambda frame: "esc back" in frame and "Opus 5.5" in frame
                           and "Haiku 4.5" in frame)
        return term, screen

    def test_the_heads_stand_where_they_stood_whatever_is_marked(self):
        for columns in (100, 60):       # with the bars, and where they have given way
            with self.subTest(columns=columns):
                self.assertEqual(heads(self.open_c(f"acme-bare-{columns}", BARE, columns)[1]),
                                 heads(self.open_c(f"acme-full-{columns}", FULL, columns)[1]))

    def test_on_40_cells_roles_fold_under_whole_names_and_stay_fixed_across_marks_and_steps(self):
        term, before = self.open_c("acme-narrow", {
            "orchestrator": "opus", "workers": [], "reviewers": ["haiku"]}, 40)
        self.assertIn("Opus 5.5", before)
        self.assertIn("Haiku 4.5", before)
        term.keys("Right", "Right", "Space")
        marked = term.wait(lambda frame: "[■]high" in frame)
        term.keys("Right", "Space")
        stepped = term.wait(lambda frame: "xhigh" in frame)
        self.assertEqual(role_starts(before), role_starts(marked))
        self.assertEqual(role_starts(before), role_starts(stepped))

    def test_unmarked_non_text_and_retired_efforts_neither_crash_nor_move_headings(self):
        with Home() as home:
            akconfig.write(home, {"opus": {"effort": "low", "exec_effort": 2},
                                  "haiku": {"harness": "claude", "model": "claude-haiku-4-5",
                                            "effort": "none"}},
                           orchestrator="opus", workers=[], reviewers=["haiku"])
            fakeadapter.install(home, claude="pass")
            _, frame = self.open_c("acme-int", {
                "orchestrator": "opus", "workers": [], "reviewers": ["haiku"]}, 100, home=home)
            self.assertIn("Opus 5.5", frame)
        # retired `minimal` outside Opus's catalog neither moves unmarked headings nor shifts when stepped
        _, current = self.open_c("acme-current", {
            "orchestrator": "haiku", "workers": [], "reviewers": ["haiku"],
            "efforts": {"opus": {"effort": "high", "exec_effort": "medium"}}}, 100)
        _, retired = self.open_c("acme-retired", {
            "orchestrator": "haiku", "workers": [], "reviewers": ["haiku"],
            "efforts": {"opus": {"effort": "high", "exec_effort": "minimal"}}}, 100)
        self.assertEqual(heads(current), heads(retired))
        term, marked = self.open_c("acme-marked-retired", {
            "orchestrator": "haiku", "workers": ["opus"], "reviewers": ["haiku"],
            "efforts": {"opus": {"effort": "high", "exec_effort": "minimal"}}}, 100)
        self.assertIn("minimal", marked)
        self.assertEqual(heads(marked), heads(current))
        term.keys("Right", "Right", "Space")
        after = term.wait(lambda frame: "low" in frame and "minimal" not in frame)
        self.assertEqual(heads(marked), heads(after))


if __name__ == "__main__":
    unittest.main()
