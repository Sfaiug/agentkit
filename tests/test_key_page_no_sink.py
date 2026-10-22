"""A page queued under a test's sink never reaches the owner's webhook, and a sink that is not a
URL sends no page at all, then or later.

`AK_NOTIFY_SINK` is what keeps a suite from paging the owner, and a queued page outlives the
environment that made it: a test's page still waiting when a tick runs with no sink and the
owner's webhook configured is dropped, said where the suite's own accounting fails the gate on
it, and never sent.  A `dry-run` or `off` sink is a test that pages nobody: its card counts as
paged, so no later tick queues another, and its page is marked as going nowhere and never tried
again.  Black-box: the program `AK_BIN` names runs `ak watch` from outside through
tests/fixtures/akbin.py, beside the record of a seat of tests/fixtures/akseat.py, with loopback
servers of tests/fixtures/sink.py as webhook and sink.
"""

import json
import socket
import sys
from pathlib import Path
import time
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def asking(home, *servers):
    """A Home whose next tick pages about seat acme, and reaches no server but `servers`."""
    akconfig.write(home, ["opus"])      # the audit off: a tick opens no seat of its own
    # The tick asks the public boards and the host's browser itself: every proxy names a
    # loopback port nobody listens on, and only the test's own servers are reached past them.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))
    passed = ",".join(urlsplit(server.url).netloc for server in servers)
    home.env.update(no_proxy=passed, NO_PROXY=passed)
    # A seat that closed with its question standing, its card held back by a tick five minutes
    # ago: nobody is in it, so its minute has passed.  A live seat's minute counts from its tmux
    # session's last activity, which no test can date back.
    Seat(home, "acme", alive=False)
    now = time.time()
    home.write(".agentkit/state/notify-acme.json",
               {"session": "acme", "kind": "needs", "text": "Which database should the app use?",
                "time": now - 300})
    home.write(".agentkit/state/card-acme.json",
               {"word": "needs you", "since": now - 300, "began": now - 300,
                "episode": "e" * 32, "sent": False})


def page_event(home):
    """The outbox's one event, the page about acme."""
    outbox = home.path / ".agentkit/state/notification-outbox"
    found = [json.loads(path.read_text()) for path in outbox.glob("*.json")]
    event, = [event for event in found if event.get("session") == "acme"]
    return event


def due(home, event):
    """Its next attempt a second ago, as a tick an hour later would find it."""
    home.write(f".agentkit/state/notification-outbox/{event['id']}.json",
               {**event, "next_attempt": time.time() - 1})


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class QueuedUnderTheSink(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        # opened before the sink, so that `AK_NOTIFY_SINK` names the sink
        self.webhook = Sink(self.home, "/api/webhooks/7/token")
        self.addCleanup(self.webhook.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        asking(self.home, self.webhook, self.sink)

    def tick(self, env=None):
        done = self.home.ak("watch", env=env)
        self.assertEqual(done.code, 0, done.err)

    def test_once_the_sink_is_gone_its_page_is_dropped_and_never_sent_to_the_webhook(self):
        self.sink.script(503)
        self.tick()
        event = page_event(self.home)
        self.assertEqual((event["status"], event["sink"]), ("pending", True))
        due(self.home, event)
        notes = self.home.path / "sink-notes.log"
        self.tick({"AK_NOTIFY_SINK": None, "AGENTKIT_DISCORD_WEBHOOK": self.webhook.url,
                   "AK_NOTIFY_SINK_LOG": str(notes)})
        event = page_event(self.home)
        self.assertEqual((event["status"], event["error"], event["next_attempt"]),
                         ("disabled", "queued under AK_NOTIFY_SINK", None))
        self.assertEqual(self.webhook.requests, [])
        self.assertEqual(len(self.sink.requests), 1)
        said, = notes.read_text().splitlines()
        self.assertIn(event["id"], said)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASinkThatIsNoURL(unittest.TestCase):
    def test_the_tick_sends_nothing_and_marks_its_page_as_going_nowhere_for_good(self):
        for marker in ("dry-run", "off"):
            with self.subTest(marker), Home() as home, \
                    Sink(home, "/api/webhooks/7/token") as webhook:
                asking(home, webhook)
                env = {"AK_NOTIFY_SINK": marker, "AGENTKIT_DISCORD_WEBHOOK": webhook.url}
                done = home.ak("watch", env=env)
                self.assertEqual(done.code, 0, done.err)
                self.assertTrue(any(line.startswith("notify: no webhook configured; message: "
                                                    "Needs you · acme")
                                    for line in done.err.splitlines()), done.err)
                event = page_event(home)
                self.assertEqual((event["status"], event["attempts"], event["receipt"]),
                                 ("disabled", 1, {}))
                card = json.loads((home.path / ".agentkit/state/card-acme.json").read_text())
                self.assertIs(card["sent"], True)
                # a page that went nowhere is never tried again
                due(home, event)
                self.assertEqual(home.ak("watch", env=env).code, 0)
                event = page_event(home)
                self.assertEqual((event["status"], event["attempts"]), ("disabled", 1))
                self.assertEqual(webhook.requests, [])


if __name__ == "__main__":
    unittest.main()
