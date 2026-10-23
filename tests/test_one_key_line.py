"""Every screen's key line leads the same way, wherever its highlight is: `↑↓←→ move   ⏎ choose`.

The walk: `menu.show_config` in a child process on a pty of its own (tests/test_config_matrix.py's
Screen, a temporary HOME), from a model's mark up onto the For row and a meter, down to a
model's effort and name, through every row under the models, and into Subscriptions' page.
The main screen's line is pinned by tests/test_menu_keys.py, the past sessions' by
tests/test_past_sessions.py and the features' by tests/test_features_screen.py.  Every other
key line is built by `terminal.keys`; the few still spelled by hand are counted here.
"""

import ast
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import terminal  # noqa: E402
from test_config_matrix import (DOWN, ENTER, ESC, KEYS, LEFT, RIGHT, UP, Screen,  # noqa: E402
                                highlighted, lit, on_effort, on_mark)

# Key lines spelled outside terminal.keys, where each is, and why it is still spelled there.
SPELLED = {
    "orch.py _picking": "n's model picker: Enter starts there, its own task",
    "menu.py MODELS_KEYS": "the `r` screen: another session's #1517 reworks it",
    "menu.py MODEL_KEYS": "a model's own screen: it goes with c's Models page",
}


def spelled():
    """Where agentkit spells a key line (a ` move   ` phrase) itself: the module's top-level name
    holding it, docstrings aside."""
    found = set()
    for path in sorted((REPO / "agentkit").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for top in tree.body:
            if isinstance(top, ast.Expr):
                continue          # the module's docstring
            docs = {id(node.body[0].value) for node in ast.walk(top)
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(node)}
            if any(isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and " move   " in f" {node.value}" and id(node) not in docs
                   for node in ast.walk(top)):
                name = getattr(top, "name", None) or top.targets[0].id
                found.add(f"{path.relative_to(REPO / 'agentkit')} {name}")
    return found - {"terminal.py MOVE_KEYS"}   # the one home


class OneKeyLine(unittest.TestCase):
    def test_c_its_pages_and_lists_draw_one_key_line(self):
        self.assertEqual(KEYS.strip(), terminal.keys("esc back"))
        screen = Screen(self)
        stops = {"a model's mark": screen.frame(lambda lines: on_mark(lines, "fable"))}
        stops["the For row"] = screen.press(UP, lambda lines: highlighted(lines).split()[1:2]
                                            == ["For"])
        stops["a meter"] = screen.press(UP, lambda lines: not any(line.startswith("›")
                                                                  for line in lines))
        stops["an effort"] = screen.press(DOWN * 3 + RIGHT * 4,
                                          lambda lines: on_effort(lines, "opus"))
        stops["a model's name"] = screen.press(LEFT * 4, lambda lines: lit(lines, "opus")
                                               not in (None, "●", "■", "□", "○"))
        lines = stops["a model's name"]
        while highlighted(lines).split()[1:2] != ["Subscriptions"]:   # each row under the models
            lines = screen.press(DOWN, lambda now, was=highlighted(lines): highlighted(now) != was)
            stops[highlighted(lines)] = lines
        stops["Subscriptions' page"] = screen.press(
            ENTER, lambda lines: "subscriptions" in lines[0])
        self.assertIn("› + add a model", stops)
        self.assertEqual({where: lines[-1] for where, lines in stops.items()},
                         dict.fromkeys(stops, KEYS))
        screen.press(ESC, lambda lines: lines[0].rstrip().endswith("config")
                     or "config " in lines[0])
        screen.leave()

    def test_only_the_screens_named_spell_their_own_key_line(self):
        self.assertLessEqual(len(SPELLED), 3)
        self.assertEqual(spelled(), set(SPELLED))


if __name__ == "__main__":
    unittest.main()
