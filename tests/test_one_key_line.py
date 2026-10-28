"""Every screen's key line leads the same way, `↑↓←→ move`, then what Space and Enter do where
its highlight is.

The walk: `menu.show_config` in a child process on a pty of its own (tests/test_config_matrix.py's
Screen, a temporary HOME), from a model's mark up onto a meter, over the For line, down to a
model's effort, through every row under the models, and into Subscriptions' page.
The main screen's line is pinned by tests/test_menu_keys.py, the past sessions' by
tests/test_key_past_sessions_by_day.py and the features' by tests/test_features_screen.py.  Every other
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
from test_config_matrix import (DOWN, ENTER, ESC, NEW_KEYS, RIGHT, UP,  # noqa: E402
                                Screen, highlighted, on_effort, on_mark)

# Key lines spelled outside terminal.keys, where each is, and why it is still spelled there.
SPELLED = {
    "menu.py MODELS_KEYS": "the models screen: its arrows split, ↑↓ moving the pointer and ←→ "
                           "stepping `within`, and on `p` Space marking and every other key "
                           "typed finding, as their tasks spell them",
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
        screen = Screen(self, session=None)
        stops = {"a model's mark": screen.frame(lambda lines: on_mark(lines, "fable"))}
        stops["a meter"] = screen.press(UP, lambda lines: not any(line.startswith("›")
                                                                  for line in lines))
        stops["an effort"] = screen.press(DOWN * 2 + RIGHT,
                                          lambda lines: on_effort(lines, "opus"))
        lines = stops["an effort"]
        while highlighted(lines).split()[1:2] != ["Subscriptions"]:   # each row under the models
            lines = screen.press(DOWN, lambda now, was=highlighted(lines): highlighted(now) != was)
            stops[highlighted(lines)] = lines
        stops["Subscriptions' page"] = screen.press(
            ENTER, lambda lines: "subscriptions" in lines[0])
        self.assertIn("› Models", stops)
        # Space where a model's mark is, Enter where a meter or a row opens
        opens = [where for where in stops if where.split()[-1] in ("meter", "Models", "Subscriptions")]
        self.assertEqual({where: lines[-1] for where, lines in stops.items()},
                         {**dict.fromkeys(stops, NEW_KEYS),
                          **dict.fromkeys(opens, NEW_KEYS.replace("␣ mark", "⏎ open")),
                          "an effort": NEW_KEYS.replace("mark", "step"),
                          # Enter's word there is its lit act's
                          "Subscriptions' page": "  ↑↓←→ move   ⏎ log in again   esc back"})
        screen.press(ESC, lambda lines: lines[0].rstrip().endswith("config")
                     or "config " in lines[0])
        screen.leave()

    def test_only_the_screens_named_spell_their_own_key_line(self):
        self.assertLessEqual(len(SPELLED), 1)
        self.assertEqual(spelled(), set(SPELLED))


if __name__ == "__main__":
    unittest.main()
