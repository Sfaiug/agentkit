"""The models screen says a line per role: its head, the recommended row by its full name and
effort, its quality, what a task of Artificial Analysis's index run cost it and how many more
models are as good, `none` where no row is scored; a row Artificial Analysis has not run is
said without a cost.  On a narrow screen the count gives way, then the cost, and the name is
cut to fit, nothing else, from 40 cells up.  Under them the knob says what it means, wrapped
at words where the screen is narrow, never cut.

Offline, on test_models_screen's fixture: a throwaway HOME, rows written by hand, the keys fed in.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, matrix, menu, terminal
from agentkit.terminal import Key
import test_models_screen as screen

KNOB = "as good within ‹ 5 › points of the best; the cheapest of those wins"


class Roles(screen.Screen):
    def shown(self, width=100):
        text = self.screens([Key("char", "r"), Key("esc"), Key("esc")], width=width)
        return text.split("models · fix-api")[1].split("agentkit · config")[0]

    def test_each_role_says_its_recommendation_quality_cost_and_how_many_more_are_as_good(self):
        # opus at max is the best in every role and its xhigh as good at half the cost; astra,
        # as good at an eighth of that, is the cheapest as good to build and review
        opus, astra = self.opus, self.astra
        self.assertIn(f"orch {opus} @ xhigh 97 $4.00 a task 0 more as good "
                      f"builds {astra} @ xhigh 95 $0.50 a task 1 more as good "
                      f"reviews {astra} @ xhigh 96 $0.50 a task 1 more as good {KNOB}",
                      self.shown())

    def test_a_row_without_an_index_run_cost_is_said_without_one_and_none_without_a_row(self):
        # Artificial Analysis has not run astra
        self.store([screen.row("codex", "gpt-6-astra", "xhigh", 84.64, 95.48, 95.75)])
        astra = self.astra
        self.assertIn(f"orch {astra} @ xhigh 85 0 more as good builds {astra} @ xhigh 95 0 more as "
                      f"good reviews {astra} @ xhigh 96 0 more as good {KNOB}", self.shown())
        self.store([])                # no model to rest on: the highlight is on the knob
        self.assertIn(f"orch none builds none reviews none › {KNOB}", self.shown())

    def test_on_a_narrow_screen_the_count_gives_way_then_the_cost_and_the_name_is_cut(self):
        opus, astra = self.opus, self.astra
        shown = self.shown(width=60)
        self.assertIn(f"orch {opus} @ xhigh 97 $4.00 a task builds {astra} @ xhigh 95 $0.50 a "
                      f"task reviews {astra} @ xhigh 96 $0.50 a task {KNOB}", shown)
        shown = self.shown(width=40)
        self.assertIn(f"orch {opus} @ xhigh 97 builds {astra} @ xhigh 95 reviews {astra} @ "
                      f"xhigh 96 {KNOB}", shown)
        self.assertNotIn("…", shown)
        named = config.model_name     # a name longer than the room left: it alone is cut, its effort kept
        with patch.object(config, "model_name", side_effect=lambda cfg, name: (
                "GPT-6-Astra Long Context Preview" if name == "astra" else named(cfg, name))):
            shown = self.shown(width=40)
        self.assertIn(f"orch {opus} @ xhigh 97 builds GPT-6-Astra Long… @ xhigh 95 reviews "
                      f"GPT-6-Astra Long… @ xhigh 96 {KNOB}", shown)

    def test_the_knob_wraps_at_words_and_never_breaks(self):
        with patch.object(terminal, "layout_width", return_value=40):
            lines, places = menu.models_body(self.cfg, {}, None, {})
        self.assertEqual([terminal.plain(lines[n]) for n, (place, _) in places.items()
                          if place == menu.KNOB],
                         ["as good within ‹ 5 › points of the", "best; the cheapest of those wins"])


if __name__ == "__main__":
    unittest.main()
