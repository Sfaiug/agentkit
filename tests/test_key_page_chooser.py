"""A seat showing a chooser on its screen reads `needs you`, and pages once its card has stood.

Nobody has to say a seat is waiting: the screen says so, and the owner is paged with only the
word and the seat, once, after a minute in which nobody typed into it, so a glance at a seat
that just asked costs no page.  The chooser is left for the owner: ak presses nothing in it.
The minute counts from the seat's last activity on tmux, which starts with the session and
cannot be set back, so this file waits that one minute for the page.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, each tick boxed and reaching
only the sink's port of the test's loopback, before a seat of tests/fixtures/akseat.py on the
fixture harness tests/fixtures/adapters/echo.toml, paging tests/fixtures/sink.py.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.sink import Sink
from fixtures import akconfig

ADAPTERS = Path(__file__).resolve().parent / "fixtures" / "adapters"
CHOOSER = "Pick one\n1. yes\n2. no\npress enter to choose\n"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AChooserOnScreen(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        self.home.env["AGENTKIT_ADAPTER_DIR"] = str(ADAPTERS)
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})

    def state(self, name):
        return json.loads((self.home.path / ".agentkit/state" / name).read_text())

    def tick(self):
        done = self.home.tick(reach=[self.sink.port])
        self.assertEqual(done.code, 0, done.err)

    def tick_until_paged(self, bound=180):
        deadline = time.monotonic() + bound
        while True:
            self.tick()
            if self.sink.pages() or time.monotonic() > deadline:
                return self.sink.pages()
            time.sleep(2)

    def test_it_reads_needs_you_at_once_and_pages_its_word_and_seat_once_later(self):
        seat = Seat(self.home, "acme", model="echo", screen=CHOOSER)
        self.tick()
        word = self.state("seat-acme.json")
        self.assertEqual({key: word.get(key) for key in ("state", "word", "reason")},
                         {"state": "asking", "word": "needs you",
                          "reason": "press enter to choose"})
        card = self.state("card-acme.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", False))
        self.assertEqual(self.sink.requests, [])

        self.assertEqual(self.tick_until_paged(), ["🙋 Needs you · acme"])
        self.assertIs(self.state("card-acme.json")["sent"], True)
        self.tick()
        self.assertEqual(len(self.sink.requests), 1)
        self.assertEqual(seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
