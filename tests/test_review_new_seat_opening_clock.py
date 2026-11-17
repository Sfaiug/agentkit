"""The row `n` makes comes up out of the background from its first frame, as a page's rows do,
however long the draw that makes it takes (docs/cli-design.md, Motion): after a draw 300 ms
slow, twice the fade, it is still coming up at its first frame and 0.14 s on, and at rest 0.15 s
on.  The ak screen as tests/test_moving_lights_are_the_rainbow.py drives it, on a clock of its
own, which the slow draw moves while it lays the row out, or after, while it sets up the
progress lines that move.
"""

import unittest
from unittest.mock import patch

from test_moving_lights_are_the_rainbow import Screens
from agentkit import menu, orch, terminal

SLOW = 0.3          # seconds the draw making the row takes
REST = 1.0          # seconds after its first frame the row has long come up


class NewSeatOpening(Screens):
    def test_the_new_seat_comes_up_from_its_first_frame_after_a_slow_draw(self):
        for slowed in ("born_lines", "grow_line"):      # laying the row out, or what moves after
            with self.subTest(slowed=slowed):
                self.comes_up(slowed)

    def comes_up(self, slowed):
        self.words, self.tasks = {"fix-api": "needs you"}, {"fix-api": (4, 12)}  # none breathes
        made, typed, slow, first = getattr(menu, slowed), menu.born, [], []

        def born(found):                # the row made: the draw making it is SLOW seconds long
            slow.append(SLOW)
            return typed(found)

        def slowly(*args, **kwargs):
            self.sleep(slow.pop() if slow else 0)
            return made(*args, **kwargs)

        def at(seconds):                # a wait at `seconds` after the row's first frame
            def step():
                first[:] = first or [self.now]
                self.now = first[0] + seconds
            return step
        with patch.object(menu, slowed, slowly), patch.object(menu, "born", born), \
                patch.object(menu, "waited", lambda work, *_a, **_kw: work()), \
                patch.object(orch, "held_names", set):
            frames, _ = self.frames([None, terminal.Key("char", "n"),
                                     *map(at, (0.14, 0.15, REST))], after=0)

        def seen(seconds):
            return next(screen for when, screen, _ in reversed(frames)
                        if when == first[0] + seconds)
        row = self.cells(seen(REST), "▏", ".")[0][0]
        cells = sorted(cell for cell in seen(REST) if cell[0] == row)

        def shown(seconds):
            return [seen(seconds).get(cell) for cell in cells]
        self.assertNotEqual(shown(0), shown(REST), "at rest from its first frame")
        self.assertNotEqual(shown(0.14), shown(REST), "at rest 0.14 s on")
        self.assertEqual(shown(0.15), shown(REST), "still coming up 0.15 s on")


if __name__ == "__main__":
    unittest.main(verbosity=2)
