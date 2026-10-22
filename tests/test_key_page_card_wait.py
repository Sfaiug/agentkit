"""A question is paged only once it has stood a minute: one asked seconds ago waits.

A question can be over within moments, seen by the owner in the seat or passed by the seat
itself, and a page for each would interrupt the owner with nothing that still needs them.  So
the tick sends a question's page only once it has stood a minute, counted from when the seat
asked it, not from the tick that first saw it.  Two seats nobody has opened for a minute ask
in the same tick, one 5 seconds ago and one 5 minutes ago: only the older is paged, and the
newer's card waits unsent.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py, paging tests/fixtures/sink.py.
"""

import json
import socket
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

QUESTION = "Which database should the app use?"
MINUTE = 60
ASKED_AGO = {"acme": 5, "beta": 300}


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CardWait(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        # The tick fetches the public model boards over https: a proxy that refuses every
        # connection keeps it off the network, whichever build runs.
        refused = socket.socket()
        refused.bind(("127.0.0.1", 0))
        cls.addClassCleanup(refused.close)
        home.env["HTTPS_PROXY"] = home.env["https_proxy"] = (
            f"http://127.0.0.1:{refused.getsockname()[1]}")
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(home, ["opus"])
        for name in ASKED_AGO:
            Seat(home, name)
        opened = time.monotonic()
        # tmux keeps when someone last typed in or opened a seat, and nothing back-dates it:
        # the seats sit out the owner's minute in real time, once, so only the question's own
        # age can hold a page back.
        time.sleep(max(0.0, opened + MINUTE + 0.5 - time.monotonic()))
        for name, ago in ASKED_AGO.items():
            home.write(f".agentkit/state/notify-{name}.json",
                       {"session": name, "kind": "needs", "text": QUESTION,
                        "time": time.time() - ago})
        done = home.ak("watch")
        assert done.code == 0, done.out + done.err

    def test_a_question_asked_seconds_ago_is_not_paged_yet(self):
        self.assertNotIn("🙋 Needs you · acme", self.sink.pages())
        card = state(self.home, "card-acme.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", False))

    def test_one_that_has_stood_a_minute_is_paged_in_the_same_tick(self):
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · beta"])
        self.assertIs(state(self.home, "card-beta.json")["sent"], True)


if __name__ == "__main__":
    unittest.main()
