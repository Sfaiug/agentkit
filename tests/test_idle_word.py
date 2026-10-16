"""`idle` is a seat's fourth word: drawn quiet, sorted last in its project, counted nowhere.

A seat with nothing running, asked or owed reads `idle` (the owner's rule of 14 Oct 2026).
Here: every screen that draws a word draws it, as `○ idle` in the dim tone (`o idle` without
UTF-8); a project's seats sort it last; the top line and the seat bars' tallies leave it out;
and the hover sentence every word has is there for it too, so nothing that looks a word up
raises on it.  Offline, no tmux.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import menu, orch, statusbar, terminal


class IdleWord(unittest.TestCase):
    def test_it_is_drawn_quiet_wherever_a_word_is(self):
        with patch.object(terminal, "utf8", return_value=True):
            self.assertEqual(terminal.state_text("idle"), "○ idle")
            self.assertIn("○ idle", statusbar.chip("idle"))
        with patch.object(terminal, "utf8", return_value=False):
            self.assertEqual(terminal.state_text("idle"), "o idle")
        self.assertEqual(terminal.state_colour("idle"), "dim")

    def test_it_sorts_last_and_no_top_line_counts_it(self):
        words = {"acme-a": "idle", "acme-b": "done", "acme-c": "needs you", "acme-d": "working"}

        def info(cfg, number, session, *args):
            return {"name": session["name"], "word": words[session["name"]], "repo": None}

        with patch.object(menu, "v5o_seat_info", side_effect=info), \
                patch.object(orch, "checkout_of", return_value=None), \
                patch.object(orch, "checkouts", return_value=[]), \
                patch.object(orch, "project_name", return_value="no project"):
            ordered, _, needing, _ = menu.v5o_groups(None, [{"name": name} for name in words],
                                                     records=[], now=1000)
        self.assertEqual([seat["word"] for seat in ordered[0]["seats"]],
                         ["needs you", "working", "done", "idle"])
        self.assertEqual(needing, 1)
        self.assertEqual(menu.rollup(["idle", "done"]), "done")
        self.assertEqual(menu.rollup(["idle"]), "idle")

    def test_no_seat_bar_counts_it(self):
        found = [("$1", "acme-a", "idle"), ("$2", "acme-b", "working"), ("$3", "acme-c", "idle"),
                 ("$4", "acme-d", "done")]
        with patch.object(terminal, "utf8", return_value=True):
            named, folded, needing, _ = statusbar.others(found, "acme-b")
        for said in (named, folded):
            self.assertNotIn("idle", said)
            self.assertIn("✓ 1 done", said)
        self.assertFalse(needing)


if __name__ == "__main__":
    unittest.main()
