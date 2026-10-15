"""A model's own screen on `c` sets the efforts it executes and reviews at.

`config · <name>` has `executes at` and `reviews at` under `effort`, each stepped with ←/→
within that model's efforts as `effort` is, and reading `same`, dim, while its key is unset: a
step leaves `same` from the effort, one back onto the effort unsets the key again, and so does a
model id change that lands a role's effort on the effort that follows the new model; the effort's
own step, here or on the `c` matrix, moves neither key, onto one of them included.  `Remove`
stays the last row.

Offline: the fake harness and throwaway HOME of tests/test_effort_per_role.py, whose catalog's
second model takes fewer efforts; the keys fed in, nothing run.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, menu, terminal
from test_effort_per_role import Acme, ROLES

ROWS = ["model id", "effort", "executes at", "reviews at", "Remove"]


class ModelScreenRoles(Acme):
    def on(self, model, effort, roles):
        """The config on `model` at `effort` with those role lines."""
        self.write(roles)
        self.path.write_text(self.path.read_text().replace('model = "acme-1"', f'model = "{model}"')
                             .replace('effort = "xhigh"', f'effort = "{effort}"'))
        return config.load()

    def keys(self, cfg, *names):
        """The screen driven by those keys then Esc: the two keys as saved, and their rows."""
        with patch.object(terminal, "read_key",
                          side_effect=[terminal.Key(name) for name in (*names, "esc")]), \
                redirect_stdout(io.StringIO()):
            menu.config_model(cfg, "acme")
        saved = tomllib.loads(self.path.read_text())["models"]["acme"]
        return (saved.get("exec_effort"), saved.get("review_effort")), \
            menu.model_body(cfg, "acme")[0][2:4]

    def test_each_role_row_steps_within_the_model_s_efforts_and_remove_stays_last(self):
        cfg = self.write("")
        lines, places = menu.model_body(cfg, "acme")
        self.assertEqual([row for row, _ in places.values()], ROWS)
        self.assertEqual(lines[:5], ["  model id     ‹ acme-1 ›", "  effort       ‹ xhigh ›",
                                     "  executes at  ‹ same ›", "  reviews at   ‹ same ›",
                                     "  Remove"])
        with patch.object(terminal, "colour_depth", return_value=8):
            self.assertIn("\033[2msame\033[0m", menu.model_body(cfg, "acme")[0][2])
        # a step leaves `same` from the effort, stops at the model's last, and back onto the
        # effort is `same` again
        self.assertEqual(self.keys(cfg, "down", "down", "right"),
                         (("max", None), ["  executes at  ‹ max ›", "  reviews at   ‹ same ›"]))
        self.assertEqual(self.keys(cfg, "down", "down", "right")[0], ("max", None))
        self.assertEqual(self.keys(cfg, "down", "down", "left")[0], (None, None))
        self.assertEqual(self.keys(cfg, "down", "down", "down", "left", "left", "left", "left"),
                         ((None, "low"), ["  executes at  ‹ same ›", "  reviews at   ‹ low ›"]))
        self.assertEqual(self.keys(cfg, "down", "down", "down", "left")[0], (None, "low"))
        # the effort row is the seat's, and moves neither: stepped onto a role's own effort, that
        # key stays set, and so does its row
        self.assertEqual(self.keys(cfg, "down", "left")[0], (None, "low"))
        self.assertEqual(cfg["models"]["acme"]["effort"], "high")
        self.assertEqual(self.keys(cfg, "down", "left", "left")[0], (None, "low"))
        self.assertEqual(cfg["models"]["acme"]["effort"], "low")
        with patch.object(terminal, "colour_depth", return_value=8):
            self.assertEqual(menu.model_body(cfg, "acme")[0][3], "  reviews at   ‹ low ›")
        # the matrix's effort step, round through every effort, keeps both keys too
        cfg = self.write(ROLES)
        for _ in range(5):
            self.assertEqual(menu.config_effort(cfg, "acme", 1, wrap=True), "")
        saved = tomllib.loads(self.path.read_text())["models"]["acme"]
        self.assertEqual((saved["effort"], saved["exec_effort"], saved["review_effort"]),
                         ("xhigh", "max", "high"))

    def test_a_model_id_change_moves_each_role_s_effort_to_one_the_new_model_takes(self):
        cfg = self.write('exec_effort = "max"\nreview_effort = "low"\n')
        self.assertEqual(self.keys(cfg, "right"),      # acme-2 takes low and medium
                         ((None, "low"), ["  executes at  ‹ same ›", "  reviews at   ‹ low ›"]))
        saved = tomllib.loads(self.path.read_text())["models"]["acme"]
        self.assertEqual((saved["model"], saved["effort"]), ("acme-2", "medium"))
        # back on the first model, which takes them all, every effort stays where it is
        cfg = self.on("acme-2", "medium", 'exec_effort = "low"\n')
        self.assertEqual(self.keys(cfg, "left"),
                         (("low", None), ["  executes at  ‹ low ›", "  reviews at   ‹ same ›"]))
        saved = tomllib.loads(self.path.read_text())["models"]["acme"]
        self.assertEqual((saved["model"], saved["effort"]), ("acme-1", "medium"))


if __name__ == "__main__":
    unittest.main()
