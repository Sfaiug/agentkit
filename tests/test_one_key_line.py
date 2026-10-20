"""Every screen's key line leads the same way, wherever its highlight is: `↑↓←→ move   ⏎ choose`.

The walk: `menu.show_config` in a child process on a pty of its own (tests/test_config_matrix.py's
Screen, a temporary HOME), from the first model up onto the For row and a meter, across a
model's marks to its effort, down to the rows under the models, and into Subscriptions' page.
The main screen's line is pinned by tests/test_menu_keys.py, the past sessions' by
tests/test_past_sessions.py and the features' by tests/test_features_screen.py.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import terminal  # noqa: E402
from test_config_matrix import (DOWN, ENTER, ESC, KEYS, RIGHT, UP, Screen,  # noqa: E402
                                highlighted, on_effort, on_mark, row)


class OneKeyLine(unittest.TestCase):
    def test_c_its_pages_and_lists_draw_one_key_line(self):
        self.assertTrue(KEYS.strip().startswith(terminal.MOVE_KEYS[0]))
        screen = Screen(self)
        stops = {"a model's mark": screen.frame(lambda lines: on_mark(lines, "fable"))}
        stops["the For row"] = screen.press(UP, lambda lines: highlighted(lines).split()[1:2]
                                            == ["For"])
        stops["a meter"] = screen.press(UP, lambda lines: not any(line.startswith("›")
                                                                  for line in lines))
        lines = stops["an effort"] = screen.press(DOWN * 3 + RIGHT * 3,
                                                  lambda lines: on_effort(lines, "opus"))
        # down past every model under opus, each an indented row, to the first row under them
        under = lines[row(lines, "opus")[0]:[line.strip() for line in lines].index("Models") + 1]
        down = sum(1 for line in under if line.startswith("  "))
        stops["Models"] = screen.press(DOWN * down, lambda lines: highlighted(lines).split()[1:2]
                                       == ["Models"])
        stops["Subscriptions"] = screen.press(
            DOWN, lambda lines: highlighted(lines).split()[1:2] == ["Subscriptions"])
        stops["Subscriptions' page"] = screen.press(
            ENTER, lambda lines: "subscriptions" in lines[0])
        self.assertEqual({where: lines[-1] for where, lines in stops.items()},
                         dict.fromkeys(stops, KEYS))
        screen.press(ESC, lambda lines: lines[0].endswith("config") or "config " in lines[0])
        screen.leave()


if __name__ == "__main__":
    unittest.main()
