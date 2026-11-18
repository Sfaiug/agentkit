"""On a terminal of eight rows, where nothing moves, the Stop card over a working seat whose runs
are still being counted is drawn once: past the whole screen's ten seconds nothing draws it again,
which would scroll the terminal, until a key, a resize or the count lands.

Black-box: ak runs in a terminal of tests/fixtures/akterm.py over a real seat of
tests/fixtures/akseat.py.  The count is held on a run whose record is a FIFO nobody writes until
the test is done, and how often the card is drawn is read from the program's own bytes, by
`pipe-pane`.
"""

import os
import re
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

NAME = "atoll-fix"
QUESTION = f"Stop {NAME} and everything it runs?"
COUNTING = "Its runs stop with it"
WHOLE = 10 + 2          # past the whole screen's draw, every ten seconds, and a margin
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[^\[\]])")


class CountingCard(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        Seat(self.home, NAME, screen="claude-working-pane.txt",
             record={"created": int(time.time()) - 900})
        self.menu = Terminal(self.home, "attach", "--overlay", size=(100, 8),
                             env={"AGENTKIT_SESSION": NAME})
        self.menu.wait(NAME)
        held = self.home.path / ".agentkit" / "runs" / "20260101-0000-held"
        held.mkdir(parents=True)
        self.record = held / "run.json"
        os.mkfifo(self.record)
        self.addCleanup(self.release)
        self.bytes = self.home.root / "program-bytes"
        done = self.home.tmux("pipe-pane", "-t", self.menu.pane,
                              f"cat >{shlex.quote(str(self.bytes))}", server=SERVER)
        self.assertEqual(done.code, 0, done.err)

    def release(self):
        """Every reader held on the record ends, on an empty one."""
        try:
            os.close(os.open(self.record, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass                # nobody is reading it

    def drawn(self):
        said = self.bytes.read_bytes().decode("utf-8", "replace") if self.bytes.exists() else ""
        return ANSI.sub("", said).count(QUESTION)

    def test_the_card_its_runs_still_counted_is_drawn_once(self):
        self.menu.keys("x")
        screen = self.menu.wait(QUESTION)
        self.assertIn(COUNTING, screen)        # still counted
        time.sleep(WHOLE)
        self.assertEqual(self.drawn(), 1)
        self.assertIn(QUESTION, self.menu.screen())
        self.menu.keys("Escape")
        self.release()
        self.menu.wait(lambda screen: QUESTION not in screen)


if __name__ == "__main__":
    unittest.main()
