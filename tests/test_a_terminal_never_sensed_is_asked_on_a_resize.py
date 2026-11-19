"""A terminal `sense` never asked is asked all the same by the screen written on it resized.

No caller has to have sensed (`terminal.sense`) for a card to let go the click its terminal sent
before it had the card: `terminal.written` asks for the terminal's attributes itself.  The card
is `terminal.confirm`'s on a keyboard only taken, in a child on a pty this test is the terminal
of: up on forty columns by eight rows, then given eighteen and told of no resize, so Down is what
draws it again, `× Remove` on row 7.  All the terminal sends is in before the card reads any of
it, in the terminal's order, as tests/test_palette.py has `sense`'s answers in: no wait runs out.
"""

import fcntl
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

CARD = """
import sys
from contextlib import closing
sys.path.insert(0, sys.argv[1])
from agentkit import terminal


def draw(card, keys):
    terminal.frame("acme", card, keys)
    return 3


with closing(terminal.Keyboard()) as keyboard:
    keyboard.take()
    removed = terminal.confirm("Remove fix-api?", "Nothing new starts on it.", "Remove", draw)
sys.exit(3 if removed else 2)       # never a crash's 1
"""
DOWN, ESC = b"\033[B", b"\033"
CLICK = b"\033[<0;3;7M\033[<0;3;7m"     # the button down and up on column 3 of row 7
SAID = b"\033[?62;22c"      # its attributes, as a terminal answers for them
HUNG = 120      # seconds with no answer: a child importing cold on a loaded host takes tens of them


class ATerminalNeverSensed(unittest.TestCase):
    def removed(self, sent):
        """Whether the card was answered Remove: `sent` is what its terminal sends once the card
        is up on eight rows and the terminal has eighteen."""
        home = self.enterContext(tempfile.TemporaryDirectory())
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 8, 40, 0, 0))
        card = subprocess.Popen(
            [sys.executable, "-c", CARD, str(Path(__file__).resolve().parents[1])], stdin=slave,
            stdout=slave, stderr=slave, start_new_session=True,
            env={"HOME": home, "TERM": "xterm-256color", "NO_COLOR": "1", "LANG": "C.UTF-8"})
        self.addCleanup(card.wait)
        self.addCleanup(card.kill)          # this test's own child, and nothing else
        shown, due = b"", time.monotonic() + HUNG
        while b"esc back" not in shown:     # its key line, the last of it
            self.assertTrue(select.select([master], [], [], max(0, due - time.monotonic()))[0],
                            shown)
            shown += os.read(master, 65536)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 18, 40, 0, 0))
        os.write(master, sent)
        return {2: False, 3: True}[card.wait(HUNG)]

    def test_no_click_it_sent_before_its_answer_answers_the_card_and_one_after_does(self):
        self.assertFalse(self.removed(DOWN + CLICK + SAID + ESC))
        self.assertTrue(self.removed(DOWN + SAID + CLICK))


if __name__ == "__main__":
    unittest.main()
