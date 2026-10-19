"""On a screen too narrow for the models table, once the harness and the cost have given way,
each model takes two lines instead of a cut label: its label and harness on the first, its
effort and its numbers on the second, the highlight on both, so a 40-cell phone reads every
model whole.  On a screen wide enough each model keeps one line (tests/test_models_screen.py).
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import terminal
from agentkit.terminal import Key
import test_models_screen as screen


class Phone(screen.Screen):
    def test_each_model_takes_two_lines_its_label_and_harness_over_its_numbers(self):
        with patch.object(terminal, "height", return_value=40):
            text = self.screens([Key("char", "r"), Key("down"), Key("esc"), Key("esc")], width=40)
        shown = text.split("models · fix-api")[1].split("agentkit · config")[0]
        self.assertIn("model harness effort orch builds reviews › opus claude ‹ xhigh › 97 97 97 "
                      "astra codex xhigh 85 95 96 claude-sonnet-5-5 claude max 68 85 85", shown)
        self.assertNotIn("…", shown)
        self.assertNotIn("cost $", shown)


if __name__ == "__main__":
    unittest.main()
