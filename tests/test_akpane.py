"""The answer key's harness pane: tests/fixtures/akpane.py in a tmux pane, as ak meets one.

A seat test reads what ak typed from the pane; it holds only if the pane keeps each line
entered whatever reads its keys arrive in, and says by its title once a frame is on the screen:
a paste split anywhere, an Esc ak types before its own text, a draft taller than the pane, and
text whose cells are not one per character.
"""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akpane import stamp

PANE = Path(__file__).resolve().parent / "fixtures" / "akpane.py"
PROMPT = "one\n\n❯ \n── footer\n"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Pane(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.screen, self.typed = self.home.root / "screen.txt", self.home.root / "typed"
        self.show(PROMPT, start=True)

    def show(self, screen, start=False):
        """The pane's next frame, once its title says it is drawn behind every key typed."""
        self.screen.write_text(screen, encoding="utf-8")
        if start:
            done = self.home.tmux("new-session", "-d", "-x", "20", "-y", "5", "-P", "-F",
                                  "#{pane_id}", shlex.join([sys.executable, str(PANE),
                                                            str(self.screen), str(self.typed)]))
            self.pane = done.out.strip()
        until(lambda: self.title() == stamp(screen.encode(), self.count()), "the frame drawn")
        return self.home.tmux("capture-pane", "-p", "-t", self.pane).out

    def title(self):
        return self.home.tmux("display-message", "-p", "-t", self.pane, "#{pane_title}").out[:-1]

    def count(self):
        return self.typed.stat().st_size if self.typed.exists() else 0

    def keys(self, *keys, literal=False):
        """Keys reaching the pane in a read of their own: each is sent once the last landed."""
        for key in keys:
            before = self.count()
            self.home.tmux("send-keys", "-t", self.pane, *(["-l"] if literal else []), key)
            until(lambda: self.count() > before, f"the pane read {key!r}")

    def lines(self, count):
        """The lines entered once there are `count` of them."""
        path = self.typed.with_name("typed.lines")

        def read():
            return [json.loads(line) for line in path.read_text().splitlines()] \
                if path.exists() else []
        until(lambda: len(read()) >= count, f"{count} lines entered")
        return read()

    def test_a_paste_is_one_line_however_its_marks_are_split(self):
        self.home.tmux("set-buffer", "-b", "clip", "first\nsecond")
        self.home.tmux("paste-buffer", "-p", "-b", "clip", "-t", self.pane)
        self.keys("Enter")
        # split inside a mark, and right after its Esc
        self.keys("\x1b[20", "0~ship\x1b[201~\r", literal=True)
        self.keys("\x1b", "[200~it\x1b[201~\r", literal=True)
        self.assertEqual(self.lines(3), ["first\nsecond", "ship", "it"])

    def test_an_esc_ak_types_before_its_text_is_the_esc_key(self):
        self.keys("Escape")
        self.keys("[audit] look", literal=True)
        self.keys("BSpace", "Enter")
        self.assertEqual(self.lines(1), ["[audit] loo"])

    def test_a_draft_taller_than_the_pane_scrolls_as_a_terminal_does(self):
        self.keys("\x1b[200~draft\rtaller\rthan\rthe\rpane\x1b[201~", literal=True)
        shown = self.show("next\n\n❯ \n── footer\n")
        self.assertEqual(shown.split(), ["taller", "than", "the", "pane", "──", "footer"])
        self.keys("Enter")
        self.assertEqual(self.lines(1), ["draft\ntaller\nthan\nthe\npane"])

    def test_a_draft_of_combining_and_wide_text_is_drawn_as_typed(self):
        self.keys("e\u0301" * 12 + "漢字", literal=True)
        self.assertIn("❯ " + "e\u0301" * 12 + "漢字", self.show("next\n\n❯ \n── footer\n"))


def until(test, what, bound=30):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"after {bound} s, still not: {what}")
        time.sleep(0.02)


if __name__ == "__main__":
    unittest.main()
