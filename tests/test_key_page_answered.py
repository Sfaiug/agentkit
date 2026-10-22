"""A question that is over before its page went out never pages the owner.

The webhook can be down when a seat asks, and its page then waits in the outbox for a retry.
If the owner answers the question in the seat meanwhile, or it is cleared, that page would
call them back to a question already settled.  So the page is retired unsent, and no tick
sends it, while one whose question still stands keeps waiting for its retry.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before seats of
tests/fixtures/akseat.py whose hooks fire as Claude fires them (tests/fixtures/hookdrive.py),
paging tests/fixtures/sink.py, which answers every page 503.
"""

import json
import socket
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks
from fixtures.sink import Sink
from fixtures import akconfig

OVER = ("disabled", "the question it asked is over")
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def offline(home):
    """A tick asks the public model boards over HTTP itself, not through a tool on PATH: every
    proxy an HTTP client honours names a loopback port nobody listens on, and only the sink, on
    loopback, is reached directly."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"),
                    no_proxy="127.0.0.1,localhost", NO_PROXY="127.0.0.1,localhost")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PageOfAQuestionOver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        offline(cls.home)
        akconfig.write(cls.home, ["opus"])    # with no audit seat for a tick to open
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        cls.sink.script(*[503] * 100)
        cls.hooks = Hooks(cls.home)

    def page(self, seat):
        """The seat's one page in the outbox, as (status, error)."""
        found = [json.loads(path.read_text()) for path in
                 (self.home.path / ".agentkit/state/notification-outbox").glob("*.json")]
        event, = [event for event in found if event.get("session") == seat]
        return event["status"], event.get("error")

    def posts(self, seat):
        return [page for page in self.sink.pages() if page == f"🙋 Needs you · {seat}"]

    def asked(self, seat, question):
        """The seat asks while the webhook is down: its page is refused and waits."""
        done = self.home.ak("notify", "needs", question, "--session", seat)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(len(self.posts(seat)), 1)
        self.assertEqual(self.page(seat), ("pending", "HTTP 503"))

    def tick(self):
        done = self.home.ak("watch")
        self.assertEqual(done.code, 0, done.err)

    def test_a_page_whose_question_stands_waits_and_once_answered_is_never_sent(self):
        seat = Seat(self.home, "fix-api")
        self.asked("fix-api", "Which schema?")
        self.tick()
        self.assertEqual(self.page("fix-api"), ("pending", "HTTP 503"))
        self.hooks.prompt("the second one", seat)
        deadline = time.monotonic() + 10    # the hook records the answer a moment after
        while self.page("fix-api") != OVER and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.page("fix-api"), OVER)
        self.tick()
        self.assertEqual(self.page("fix-api"), OVER)
        self.assertEqual(len(self.posts("fix-api")), 1)

    def test_a_page_whose_question_was_cleared_is_retired_by_the_next_tick(self):
        Seat(self.home, "fix-web")
        self.asked("fix-web", "Which port?")
        (self.home.path / ".agentkit/state/notify-fix-web.json").unlink()
        self.tick()
        self.assertEqual(self.page("fix-web"), OVER)
        self.tick()
        self.assertEqual(len(self.posts("fix-web")), 1)


if __name__ == "__main__":
    unittest.main()
