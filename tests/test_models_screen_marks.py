"""The models screen lists every model the matrix has a row for, which is every model the
installed harnesses offer, under its harness as `c` lists models under a provider: the
harnesses by name, each one's models by their best quality, a line each with its mark, filled
where it is assessed (matrix.assessed: `[assess]`, else every model the config runs), its full
name where the config runs it, else its id, and the id after a full name, dim.  Space, Enter
or a click on a model flips its mark, saved to config.toml at once, and the recommendation
follows.  A 40-cell phone reads a 35-cell id whole.

Offline, on test_models_screen's fixture: a throwaway HOME, rows written by hand, the keys fed in.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, terminal
from agentkit.terminal import Key
import test_models_screen as screen


class Marks(screen.Screen):
    def test_every_model_under_its_harness_marked_where_the_config_runs_it(self):
        text = self.screens([Key("char", "r"), Key("esc"), Key("esc")])
        # sonnet and mimo, which no seat's config runs, unmarked; opus over sonnet, the better
        self.assertIn(f"Claude Code › ■ {self.opus} claude-opus-5-5 □ claude-sonnet-5-5 Codex ■ "
                      f"{self.astra} gpt-6-astra Muse Code ■ {self.spark} OpenCode □ mimo-pro", text)

    def test_space_flips_a_mark_saved_at_once_and_the_recommendation_follows(self):
        # opus unmarked: astra, the one marked model scored, is recommended in every role
        text = self.screens([Key("char", "r"), Key("space"), Key("esc"), Key("esc")])
        marks = config.load()["assess"]           # every other model the config runs stays
        self.assertNotIn("claude-opus-5-5", marks["claude"])
        self.assertEqual(marks["codex"], ["gpt-6-astra"])
        self.assertIn(f"orch {self.astra} @ xhigh 85", text)
        self.assertIn(f"Claude Code › □ {self.opus}", text)
        # Enter on sonnet marks it, beside the marks as saved
        self.screens([Key("char", "r"), Key("down"), Key("enter"), Key("esc"), Key("esc")])
        self.assertEqual({**marks, "claude": sorted([*marks["claude"], "claude-sonnet-5-5"])},
                         config.load()["assess"])

    def test_a_click_on_a_model_flips_its_mark(self):
        spots, frame = {}, terminal.frame

        def framed(*args, **kwargs):
            drawn = frame(*args, **kwargs)
            spots.update(drawn)
            return drawn

        def keys():         # a click on mimo's name, where the models screen drew it
            yield Key("char", "r")
            yield next(Key("click", col=first + 4, row=line)
                       for line, (row, cells) in spots.items() if row == ("model", "opencode", "mimo-pro")
                       for first, *_ in cells)
            yield Key("esc")
            yield Key("esc")
        with patch.object(terminal, "frame", side_effect=framed):
            self.screens(keys())
        self.assertIn("mimo-pro", config.load()["assess"]["opencode"])

    def test_a_phone_reads_a_long_id_whole(self):
        self.store([screen.row("opencode", "opencode/nemotron-3.5-super-vl-free", None, None, 50.71,
                               51.79, cost=0.1)])
        with patch.object(terminal, "height", return_value=40):
            text = self.screens([Key("char", "r"), Key("esc"), Key("esc")], width=40)
        self.assertIn("OpenCode › □ opencode/nemotron-3.5-super-vl-free", text)


if __name__ == "__main__":
    unittest.main()
