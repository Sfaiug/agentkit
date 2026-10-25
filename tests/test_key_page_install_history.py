"""Nothing from before the running install pages: an upgrade finds old words standing, no news.

install.sh stamps state/installed-at.  An upgrade finds every seat's word already standing, and
a question whose episode began before that stamp is history: no tick pages it, however long it
has stood, while the same question with no install to be older than pages once.  A page the
webhook refused before the install, queued for its retry, is history too: the tick drops it
unsent, its event saying why, and posts nothing.  A page that comes late only interrupts the
owner with what he has already seen.  Neither tick touches the owner's units or logins.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before
seats of tests/fixtures/akseat.py, paging tests/fixtures/sink.py.
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

QUESTION = "Which database should the app use?"
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
HOST = ("systemctl", "systemd-run", "loginctl", "journalctl")
LATE = "queued before the agentkit running now was installed"


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


def events(home):
    """Every event in the outbox."""
    return [json.loads(path.read_text())
            for path in (home.path / ".agentkit/state/notification-outbox").glob("*.json")]


def installed(home, ago):
    """Stamp the install as install.sh does, in whole seconds, `ago` seconds back."""
    home.write(".agentkit/state/installed-at", f"{int(time.time()) - ago}\n")


class Paging(unittest.TestCase):
    def home(self, *replies):
        """A Home whose ticks reach the sink and nothing else: the tick asks the public model
        boards and the host's browser over HTTP itself, so every proxy names a loopback port
        nobody listens on, and only the sink goes direct."""
        home = Home()
        self.addCleanup(home.close)
        sink = Sink(home)
        self.addCleanup(sink.close)
        sink.script(*replies)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))
        passed = urlsplit(sink.url).netloc
        home.env.update(no_proxy=passed, NO_PROXY=passed)
        akconfig.write(home, ["opus"])      # the audit off: a tick opens no seat of its own
        # a collection on record from just now: a due one sweeps the host's own /tmp
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        return home, sink

    def tick(self, home):
        done = home.ak("watch")
        self.assertEqual(done.code, 0, done.out + done.err)

    def untouched_host(self, home):
        for tool in HOST:
            self.assertEqual(home.calls(tool), [], tool)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class QuestionBeforeTheInstall(Paging):
    def asked_five_minutes_ago(self):
        """acme's question, asked five minutes ago, and the episode a tick opened for it then.

        tmux lost the seat, so nobody is in it and its card waits for no key of the owner's: a
        live seat's session would be seconds old, and that minute counts from its last
        activity, which nothing back-dates.  Its conversation is not its own, so no tick
        reopens it to ask again."""
        home, sink = self.home()
        Seat(home, "acme", alive=False, record={"id_source": None})
        asked = time.time() - 300
        home.write(".agentkit/state/notify-acme.json",
                   {"session": "acme", "kind": "needs", "text": QUESTION, "time": asked})
        self.tick(home)
        card = state(home, "card-acme.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", False))
        home.write(".agentkit/state/card-acme.json", {**card, "since": asked, "began": asked})
        return home, sink

    def test_a_question_asked_before_the_install_never_pages(self):
        home, sink = self.asked_five_minutes_ago()
        installed(home, ago=100)
        self.tick(home)
        self.tick(home)
        self.assertEqual(sink.requests, [])
        card = state(home, "card-acme.json")
        self.assertEqual((card["word"], card["sent"]), ("needs you", False))
        self.assertEqual(events(home), [])
        self.untouched_host(home)

    def test_with_no_install_to_be_older_than_the_same_question_pages_once(self):
        home, sink = self.asked_five_minutes_ago()
        self.tick(home)
        self.tick(home)
        self.assertEqual(sink.pages(), ["🙋 Needs you · acme"])
        self.assertIs(state(home, "card-acme.json")["sent"], True)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RetryBeforeTheInstall(Paging):
    def test_a_page_queued_before_the_install_is_dropped_unsent_saying_why(self):
        home, sink = self.home(503)
        Seat(home, "acme")
        done = home.ak("notify", "needs", QUESTION, "--session", "acme")
        self.assertEqual(done.code, 0, done.err)
        event, = events(home)
        self.assertEqual((event["status"], event["attempts"]), ("pending", 1))
        # queued before the install, and its retry due now
        now = time.time()
        home.write(f".agentkit/state/notification-outbox/{event['id']}.json",
                   {**event, "created_at": now - 200, "next_attempt": now - 1})
        installed(home, ago=100)
        self.tick(home)
        self.tick(home)
        event, = events(home)
        self.assertEqual({key: event[key] for key in ("status", "error", "attempts",
                                                      "next_attempt")},
                         {"status": "disabled", "error": LATE, "attempts": 1,
                          "next_attempt": None})
        self.assertEqual([request.method for request in sink.requests], ["POST"])
        self.untouched_host(home)


if __name__ == "__main__":
    unittest.main()
