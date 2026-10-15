"""A subscription under the pointer washes into its company's colour, and its models with it.

The owner's design (14 Oct 2026): at rest no company's colour is on the ak screen.  Pointing at
a subscription colours its name and its meter in, left to right with a light riding the edge,
and every seat's model that runs on it lights the same way; it drains when the pointer leaves.
Offline: a temporary HOME, fake seats, no tmux, the pointer set by hand.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, motion, terminal  # noqa: E402

CLAUDE = menu.COLOURS["anthropic"]


class Wash(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": "at_prompt", "rule": "fixture", "since": 9100,
                                       "began": 9100, "evidence": ""}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        directory = config.CODE / "acme"
        directory.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(directory)], check=True)
        self.seats = [{"name": name, "repo": str(directory), "path": str(directory),
                       "created": 9000} for name in ("acme-plan", "acme-docs")]
        for name, model in (("acme-plan", "opus"), ("acme-docs", "astra")):
            config.save_session(self.cfg, name, model, ["opus"],
                                {"repo": str(directory), "cwd": str(directory)})

    def screen(self, pointer=None, clock=None):
        terminal._POINTER = pointer and terminal.Key("point", "", *pointer)
        with patch.object(terminal, "width", return_value=120), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, None, {}, look=False, clock=clock)
        return out.getvalue().split("\033[J")[0].split("\n")

    def row(self, lines, name):
        return next(line for line in lines if f" {name} " in line)

    def test_at_rest_no_model_wears_a_colour_and_the_pointer_colours_its_subscriptions(self):
        rest = self.screen()
        for name, model in (("acme-plan", "opus"), ("acme-docs", "astra")):
            # its reset brightens the highlighted row again, so the end of it is the row's
            self.assertIn(terminal.styled(model, "dim")[:-1], self.row(rest, name))
        lit = self.screen((5, 3))                   # Claude, first on the grid
        self.assertIn(terminal.styled("Claude", CLAUDE), lit[2])
        self.assertIn(terminal.styled("opus", CLAUDE)[:-1], self.row(lit, "acme-plan"))
        self.assertIn(terminal.styled("astra", "dim")[:-1], self.row(lit, "acme-docs"))

    def test_coming_onto_it_starts_the_wash_on_its_name_meter_and_models(self):
        clock = motion.Clock()
        self.screen(clock=clock)
        lines = self.screen((5, 3), clock)
        row = next(n for n, line in enumerate(lines, 1) if " acme-plan " in line)
        column = terminal.plain(lines[row - 1], spaced=True).index("opus") + 1
        self.assertIn((3, 3), clock.cells)                      # the C of Claude
        self.assertIn((row, column), clock.cells)               # the o of opus
        other = next(n for n, line in enumerate(lines, 1) if " acme-docs " in line)
        self.assertFalse([cell for cell in clock.cells if cell[0] == other])

    def test_the_wash_runs_left_to_right_with_a_lit_edge_and_drains_back(self):
        frames, until = motion.colouring("Claude", 0.0, CLAUDE, True)
        self.assertEqual(until, motion.WASH)
        self.assertEqual([frame(0.0) for frame in frames], list("Claude"))
        self.assertEqual([frame(until) for frame in frames],
                         [terminal.styled(char, CLAUDE) for char in "Claude"])
        middle = [frame(until / 2) for frame in frames]
        self.assertEqual(middle[0], terminal.styled("C", CLAUDE))     # in from the left
        self.assertEqual(middle[-1], "e")                              # not yet at the right
        frames, until = motion.colouring("opus", 0.0, CLAUDE, False, "dim")
        self.assertEqual([frame(0.0) for frame in frames],
                         [terminal.styled(char, CLAUDE) for char in "opus"])
        self.assertEqual([frame(until) for frame in frames],
                         [terminal.styled(char, "dim") for char in "opus"])


if __name__ == "__main__":
    unittest.main()
