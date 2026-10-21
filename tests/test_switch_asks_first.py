"""Moving a seat to another orchestrator asks first on the `c` screen.

Enter, space or a click on another model's orchestrator mark asks `Move <seat> to <model>?`,
the model by its full name (config.model_name), on the one card every yes-or-no question is
asked on, drawn under the rows: `Keep` is picked until the owner moves to `Move`, and Esc keeps.  Only `Move` moves the seat; the mark of the
model the seat is already on asks nothing and moves nothing.  A slip of a key used to hand a
live conversation over at once.

Offline: a throwaway HOME, the keys fed in, the card answered by a fake `terminal.confirm`
that draws the screen around it, and the switch itself faked to write the record alone; the
card's room on a short terminal is read off the real screen on a pty (test_config_matrix's).
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
from fixtures.sandbox import Sandbox
from test_config_matrix import DOWN, ENTER, Screen, highlighted
from agentkit import config, menu, orch, terminal, update, usage
from agentkit.terminal import Key


class Keyboard:
    def take(self):
        return True


class SwitchAsksFirst(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.asked, self.moved = [], []

        def confirm(question, meaning, answer, around, wait=None):
            drawn = io.StringIO()
            with redirect_stdout(drawn):
                row = around(["<card>"])
            self.asked.append((question, meaning, answer, drawn.getvalue().split("\n")[row - 1]))
            return self.answers.pop(0)

        def switch(cfg, name, model, providers=None):
            # as the real one: the seat's own model is no move
            if config.load_session(cfg, name)["orchestrator"] == model:
                return ""
            self.moved.append((name, model))
            config.update_session(name, orchestrator=model)
            return ""
        self.stack.enter_context(patch.object(terminal, "confirm", side_effect=confirm))
        self.stack.enter_context(patch.object(orch, "switch_orchestrator", side_effect=switch))
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        self.stack.enter_context(patch.object(usage, "collect",
                                              return_value=usage.Readings({})))

    def screen(self, keys, answers):
        """The `c` screen of fix-api read with `keys`, each card answered from `answers`."""
        self.answers = list(answers)
        with patch.object(terminal, "read_key", side_effect=keys), \
                redirect_stdout(io.StringIO()):
            menu.show_config(False, Keyboard(), "fix-api")

    def test_another_model_s_orchestrator_mark_asks_and_keep_leaves_the_seat(self):
        # the highlight opens on the first model's orchestrator mark: fable's, while the seat
        # is on opus
        self.screen([Key("enter"), Key("esc")], [False])
        fable = config.model_name(self.cfg, "fable")
        self.assertEqual([(q, a) for q, _, a, _ in self.asked],
                         [(f"Move fix-api to {fable}?", "Move")])
        question, meaning, _, under = self.asked[0]
        self.assertEqual(meaning, menu.MOVE_ASK[1].format(fable))
        self.assertEqual(under, "<card>")        # drawn under the rows, where the row says
        self.assertEqual(self.moved, [])
        self.assertEqual(config.load_session(self.cfg, "fix-api")["orchestrator"], "opus")

    def test_move_moves_the_seat_and_the_mark_of_its_own_model_asks_nothing(self):
        # Move answers the card; then Enter on fable again, now the seat's own model
        self.screen([Key("enter"), Key("enter"), Key("esc")], [True])
        self.assertEqual([q for q, _, _, _ in self.asked],
                         [f"Move fix-api to {config.model_name(self.cfg, 'fable')}?"])
        self.assertEqual(self.moved, [("fix-api", "fable")])
        self.assertEqual(config.load_session(self.cfg, "fix-api")["orchestrator"], "fable")

    def test_a_role_mark_asks_nothing(self):
        # → to the exec column, Enter flips fable into the executors, no card
        self.screen([Key("right"), Key("enter"), Key("esc")], [])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.moved, [])
        self.assertIn("fable", config.load_session(self.cfg, "fix-api")["workers"])


# The shipped gemini as every screen names it (config.model_name).
GEMINI = config.model_name(tomllib.loads((REPO / "config.default.toml").read_text()), "gemini")


def on_gemini(lines):
    """Whether the highlight is on gemini's row, drawn by its full name -- cut, `…` last, where
    the screen is narrow."""
    label = highlighted(lines)[2:].split("  ")[0].strip()
    return label == GEMINI or label.endswith("…") and GEMINI.startswith(label[:-1])


class MoveCardFits(unittest.TestCase):
    def test_the_rows_give_the_card_room_and_the_highlight_stays_on(self):
        # 24 rows, a desk's width and a phone's: the card asked on a row near the page's foot
        # keeps the frame within the terminal, as the matrix is, with the row it asks about on
        for cols in (100, 40):
            screen = Screen(self, rows=24, cols=cols)
            lines = screen.press(DOWN * 6, on_gemini)
            self.assertLessEqual(len(lines), 23)
            asked = f"Move fix-api to {GEMINI}?"
            lines = screen.press(ENTER, lambda lines: asked in " ".join(" ".join(lines).split()))
            self.assertLessEqual(len(lines), 23, "\n".join(lines))
            self.assertTrue(on_gemini(lines), lines)
            self.assertEqual(lines[-1], "  esc back")
            lines = screen.press(DOWN + ENTER, lambda lines: on_gemini(lines)
                                 and "●" in highlighted(lines))
            self.assertEqual(screen.record()["orchestrator"], "gemini")
            screen.leave()


if __name__ == "__main__":
    unittest.main()
