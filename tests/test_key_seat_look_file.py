"""Every read of a live seat's screen writes the word it decided to the seat's file.

`~/.agentkit/state/seat-<name>.json` is where the menu, `ak orch`, the tick and the seat's own
bar meet: one of them reads the screen, decides `working`, `needs you`, `done` or `idle`, and
writes the word with why (`reason`, `rule`, `authority`, `word_from`) and since when
(`word_since`), so the next reader starts from it and a word keeps one beginning however many
screens draw it.  Black-box: each seat is a real tmux session showing a captured screen
(tests/fixtures/akseat.py), and the program `AK_BIN` names reads it from outside.
"""

import json
import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

WORDS = ("working", "needs you", "done", "idle")


def row(screen, name):
    """The line of a listing that names that seat."""
    found = [line for line in screen.splitlines() if re.search(rf"(?<!\S){name}(?!\S)", line)]
    return found[0] if found else ""


def said(line):
    """The words of WORDS that line carries."""
    return [word for word in WORDS if re.search(rf"(?<![\w-]){word}(?![\w-])", line)]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatFile(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def seat_file(self, name, bound=30):
        """The seat's file once it holds a word: a screen draws its row a moment before the
        file is written."""
        path = self.home.path / ".agentkit" / "state" / f"seat-{name}.json"
        deadline = time.monotonic() + bound
        while True:
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict) and "word" in data:
                    return data
            except (OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise AssertionError(f"{path.name} never held a word")
            time.sleep(0.05)

    def test_orch_why_writes_a_permission_question_as_needs_you_with_its_rule(self):
        Seat(self.home, "acme", screen="claude-permission-pane.txt")
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("needs you", done.out)
        data = self.seat_file("acme")
        self.assertEqual(data["word"], "needs you")
        self.assertEqual(data["state"], "asking")
        self.assertEqual(data["rule"], "asking.permission")
        self.assertEqual(data["authority"], "screen")
        self.assertEqual(data["session"], "acme")
        self.assertTrue(data["reason"])
        self.assertEqual(data["word_from"][:2], ["asking", "asking.permission"])
        self.assertIn("word_since", data)

    def test_orch_list_writes_a_seat_at_its_composer_as_idle(self):
        Seat(self.home, "beta", screen="claude-prompt-pane.txt")
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(said(row(done.out, "beta")), ["idle"])
        data = self.seat_file("beta")
        self.assertEqual(data["word"], "idle")
        self.assertEqual(data["session"], "beta")
        self.assertEqual(data["authority"], "screen")
        self.assertEqual(data["word_from"][:2], ["at_prompt", "prompt.composer"])
        for key in ("reason", "unsent", "word_since"):
            self.assertIn(key, data)
        # nothing is typed in it: the composer is empty
        self.assertEqual(data["unsent"], "")

    def test_the_menu_shows_each_seat_s_screen_as_its_word_and_writes_it_down(self):
        cwd = self.home.path / "code" / "acme"
        seats = {"fix-api": ("claude-working-pane.txt", "● working"),
                 "beta": ("claude-question-pane.txt", "! needs you"),
                 "gamma": ("claude-prompt-pane.txt", "○ idle")}
        for name, (screen, _) in seats.items():
            Seat(self.home, name, screen=screen, cwd=cwd)
        menu = Terminal(self.home, size=(100, 30))
        # The first frame is the seats' files as they stand, none yet; the look lands after it.
        menu.wait(lambda screen: all(shown in row(screen, name)
                                     for name, (_, shown) in seats.items()))
        for name, (_, shown) in seats.items():
            with self.subTest(name):
                data = self.seat_file(name)
                self.assertEqual(data["word"], shown[2:])
                for key in ("state", "rule", "evidence"):
                    self.assertIn(key, data)

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_tick_writes_a_working_seat_s_word_and_the_next_reader_keeps_its_beginning(self):
        # the weekly audit would open a seat of its own on this tick
        config = self.home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        seat = Seat(self.home, "acme", screen="claude-working-pane.txt")
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        ticked = self.seat_file("acme")
        self.assertEqual(ticked["word"], "working")
        self.assertEqual(ticked["state"], "working")
        self.assertEqual(ticked["authority"], "screen")
        self.assertEqual(ticked["session"], "acme")
        # reading is all a tick does to a seat in the middle of a turn
        self.assertEqual(seat.typed(), "")
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(said(row(done.out, "acme")), ["working"])
        listed = self.seat_file("acme")
        self.assertEqual(listed["word"], "working")
        self.assertEqual(listed["word_since"], ticked["word_since"])


if __name__ == "__main__":
    unittest.main()
