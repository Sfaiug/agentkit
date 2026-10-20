"""A screen that waits on ak's own fetch -- a catalog, a provider's list, a reset spent, what each
subscription has left -- says in words what it waits on, a spinner turning beside it.

The owner's pick of 18 Oct 2026, "a spinner for ak's own short waits".  In-process: the frame
drawn and the clock it waits on are read, the fetch is a thread held until the test lets it go,
and nothing reaches a harness or a terminal.
"""

from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import menu, motion, terminal  # noqa: E402


class Spins(unittest.TestCase):
    def wait(self, body=list, utf8=True, rows=24):
        held, drawn, clocks = threading.Event(), [], []
        self.addCleanup(held.set)

        def moving(clock, **_kw):
            clocks.append(clock)
            return terminal.Key("esc")

        with patch.object(terminal, "taken", return_value=True), \
                patch.object(terminal, "utf8", return_value=utf8), \
                patch.object(terminal, "colour_depth", return_value=24), \
                patch.object(terminal, "layout_width", return_value=60), \
                patch.object(terminal, "height", return_value=rows), \
                patch.object(terminal, "frame", lambda title, lines, keys: drawn.append(lines)), \
                patch.object(menu, "moving", moving), self.assertRaises(menu.Back):
            menu.waited(held.wait, "config · models", body,
                        doing="reading the models acme offers")
        return drawn[-1], clocks[-1]

    def test_what_it_waits_on_is_said_under_the_rule_a_spinner_turning_beside_it(self):
        lines, clock = self.wait()
        said = terminal.ANSI.sub("", lines[-1])
        self.assertEqual((said[:2], said[2] in motion.SPINNER, said[3:]),
                         ("  ", True, " reading the models acme offers"))
        spinner, until = clock.cells[2 + len(lines), 3]
        self.assertIsNone(until)                     # it turns for as long as it is drawn
        turned = {terminal.ANSI.sub("", spinner(n * motion.SPIN + motion.SPIN / 2))
                  for n in range(len(motion.SPINNER))}      # a turn, from wherever it was
        self.assertEqual(turned, set(motion.SPINNER))

    def test_under_what_the_screen_shows_after_a_blank_and_plain_without_utf8(self):
        lines, clock = self.wait(lambda: ["  picked: acme"], utf8=False)
        said = [terminal.ANSI.sub("", line) for line in lines]
        self.assertEqual(said[:2], ["  picked: acme", ""])
        self.assertRegex(said[2], r"^  [|/\\-] reading the models acme offers$")
        spinner, _ = clock.cells[2 + len(lines), 3]
        self.assertIn(terminal.ANSI.sub("", spinner(0)), "|/-\\")

    def test_left_out_where_the_screen_has_no_room_for_it_so_nothing_scrolls(self):
        body = [f"  row {n}" for n in range(12)]
        lines, clock = self.wait(lambda: body, rows=17)    # 16 lines fit, two more would not
        self.assertEqual(lines, body)
        self.assertEqual({row for row, _ in clock.cells}, {2})     # the rule glides alone
        lines, clock = self.wait(lambda: body, rows=19)
        self.assertEqual(len(lines), len(body) + 2)                 # with room, it is said


if __name__ == "__main__":
    unittest.main()
