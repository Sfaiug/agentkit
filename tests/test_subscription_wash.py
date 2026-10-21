"""A subscription under the pointer washes into its company's colour, and its models with it.

The owner's design (14 Oct 2026): at rest no company's colour is on the ak screen.  Pointing at
a subscription colours its name and its meter in, left to right with a light riding the edge,
and every seat's model that runs on it lights the same way; it drains when the pointer leaves.
On `c` the meter the highlight or the pointer is on does the same, with the models it runs.
Offline: a temporary HOME, fake seats, no tmux, the pointer set by hand.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, motion, terminal, watch  # noqa: E402

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

    def full(self, name):
        """The name a seat's row and `c` show the model by (config.model_name)."""
        return config.model_name(self.cfg, name)

    def test_at_rest_no_model_wears_a_colour_and_the_pointer_colours_its_subscriptions(self):
        rest = self.screen()
        for name, model in (("acme-plan", "opus"), ("acme-docs", "astra")):
            # its reset brightens the highlighted row again, so the end of it is the row's
            self.assertIn(terminal.styled(self.full(model), "dim")[:-1], self.row(rest, name))
        lit = self.screen((5, 3))                   # Claude, first on the grid
        self.assertIn(terminal.styled("Claude", CLAUDE), lit[2])
        self.assertIn(terminal.styled(self.full("opus"), CLAUDE)[:-1], self.row(lit, "acme-plan"))
        self.assertIn(terminal.styled(self.full("astra"), "dim")[:-1], self.row(lit, "acme-docs"))

    def test_coming_onto_it_starts_the_wash_on_its_name_meter_and_models(self):
        clock = motion.Clock()
        self.screen(clock=clock)
        lines = self.screen((5, 3), clock)
        row = next(n for n, line in enumerate(lines, 1) if " acme-plan " in line)
        column = terminal.plain(lines[row - 1], spaced=True).index(self.full("opus")) + 1
        self.assertIn((3, 3), clock.cells)                      # the C of Claude
        self.assertIn((row, column), clock.cells)               # the o of opus
        other = next(n for n, line in enumerate(lines, 1) if " acme-docs " in line)
        self.assertFalse([cell for cell in clock.cells if cell[0] == other])

    def test_the_wash_runs_left_to_right_with_a_lit_edge_and_drains_back(self):
        frame, until = motion.colouring("Claude", 0.0, CLAUDE, True)
        self.assertEqual(until, motion.WASH)
        self.assertEqual(frame(0.0), "Claude")
        self.assertEqual(frame(until), "".join(terminal.styled(char, CLAUDE) for char in "Claude"))
        middle = frame(until / 2)
        self.assertTrue(middle.startswith(terminal.styled("C", CLAUDE)))     # in from the left
        self.assertTrue(middle.endswith("e"))                                 # not yet at the right
        frame, until = motion.colouring("opus", 0.0, CLAUDE, False, "dim")
        self.assertEqual(frame(0.0), "".join(terminal.styled(char, CLAUDE) for char in "opus"))
        self.assertEqual(frame(until), "".join(terminal.styled(char, "dim") for char in "opus"))

    def test_a_meter_amber_for_its_login_drains_back_to_amber(self):
        week = {"name": "weekly", "resets_at": 10000 + 86400, "window_secs": 604800, "used": 50}
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": 10000, "providers": {"anthropic": {"meters": [week]}}}))
        (config.STATE / "logins.json").write_text(json.dumps(
            {"anthropic": {"default": {"email": "owner@acme.test", "ends": 10000 + 86400}}}))
        clock = motion.Clock()
        self.screen((5, 3), clock)
        self.screen(clock=clock)                    # the pointer leaves
        frame, until = next(cell for (row, _), cell in clock.cells.items()
                            if row == 3 and terminal.plain(cell[0](0)).startswith("▰"))
        self.assertEqual(frame(until), terminal.styled("▰", "amber") * 5)

    def test_a_wide_label_is_washed_whole_from_its_first_cell(self):
        self.cfg["providers"]["anthropic"]["name"] = "界A"
        clock = motion.Clock()
        self.screen(clock=clock)
        self.screen((5, 3), clock)
        frame, until = clock.cells[3, 3]
        self.assertEqual(terminal.plain(frame(until)), "界A")
        self.assertNotIn((3, 4), clock.cells)       # nothing written inside the wide letter

    def test_a_wide_name_or_a_model_named_as_its_number_lights_the_model_in_its_column(self):
        self.cfg["models"]["1"] = dict(self.cfg["models"]["opus"], model="1")    # shown as "1"
        seat = self.seats[0]
        seat["name"] = "acme-界"
        config.save_session(self.cfg, seat["name"], "1", ["opus"],
                            {"repo": seat["repo"], "cwd": seat["path"]})
        number, model = self.row(self.screen((5, 3)), seat["name"]).split(seat["name"])
        self.assertIn(terminal.styled("1", "dim")[:-1], number)
        self.assertIn(terminal.styled("1", CLAUDE)[:-1], model)

    def test_a_row_shorter_than_a_wider_word_beside_it_lights_its_model(self):
        watch.seat_write("acme-docs", word="working", reason="", word_since=9100)
        self.assertIn(terminal.styled(self.full("opus"), CLAUDE)[:-1],
                      self.row(self.screen((5, 3)), "acme-plan"))

    def c_keys(self, names):
        """What moves on `c`, its last frames, as each of `names`' keys and then Esc is read."""
        week = {"name": "weekly", "resets_at": 10000 + 86400, "window_secs": 604800, "used": 50}
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [week]}, "openai": {"meters": [week]}}}))
        keys, drawn = iter([*map(terminal.Key, names), terminal.Key("esc")]), []

        def key(clock=None, **_kw):       # what moves on the screen as each key is read
            drawn.append({terminal.plain(animation(until)): animation(until)
                          for animation, until in (clock.cells.values() if clock else ())
                          if until})
            return next(keys)
        with patch.object(terminal, "layout_width", return_value=100), \
                patch.object(terminal, "height", return_value=40), \
                patch.object(terminal, "taken", return_value=True), \
                patch.object(menu, "moving", side_effect=key), \
                patch.object(terminal, "read_key", side_effect=lambda *a, **k: key()), \
                redirect_stdout(io.StringIO()):
            menu.config_matrix(self.cfg, None, "abc1234")
        return drawn

    def test_on_c_the_meter_the_highlight_comes_onto_washes_in_and_its_models_with_it(self):
        drawn = self.c_keys(["up"])
        chatgpt = menu.COLOURS["openai"]     # ↑ from the first model: the last meter, ChatGPT's
        lit, astra = drawn[-1], self.full("astra")
        self.assertEqual(lit[astra], "".join(terminal.styled(char, chatgpt) for char in astra))
        self.assertIn("ChatGPT", lit)
        self.assertNotIn(self.full("opus"), lit)

    def test_on_c_a_step_between_one_company_s_meters_keeps_its_models_lit(self):
        self.cfg["providers"]["anthropic"]["accounts"] = ["default", "second"]
        drawn = self.c_keys(["up"] * 7)   # every meter back from ChatGPT, Claude II then I last
        opus = self.full("opus")
        lit = "".join(terminal.styled(char, CLAUDE) for char in opus)
        self.assertEqual(drawn[-1].get(opus, lit), lit)

    def test_a_free_slot_on_the_grid_s_last_line_lights_nothing(self):
        self.cfg["providers"]["anthropic"]["accounts"] = ["default", "second"]
        line, free = divmod(len(menu.usage_rows(self.cfg)), 3)     # three to a line at 120
        self.assertTrue(free, "the grid's last line has no free slot")
        lines = self.screen((3 + free * (menu.COLUMN + 2) + 1, 3 + line))
        self.assertIn(terminal.styled(self.full("opus"), "dim")[:-1], self.row(lines, "acme-plan"))


if __name__ == "__main__":
    unittest.main()
