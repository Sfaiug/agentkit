"""A seat resting at its prompt reads `idle` and pages nothing, and no failing probe pages.

The owner is paged only for what needs them or a finished job.  A seat at its prompt with
nothing asked or owed reads `idle`, on its record and in its terminal's title, and pages
nothing.  ak reads every harness's meters and logins on its own, and those reads fail: a harness
prints a traceback, a login file will not parse.  That is ak's to live with, never the owner's:
a usage read, a login-end read or a seat's `auth` verb that cannot answer pages nothing, even
under the harness's own logout words on the screen, since only a verb that answers no decides
that a login expired.  Black-box: the program `AK_BIN` names runs `ak usage` and `ak watch` from
outside through tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py, on the echo
harness of tests/fixtures/adapters behind tests/fixtures/fakeadapter.py, paging
tests/fixtures/sink.py.
"""

import json
import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.sink import Sink

ECHO = Path(__file__).resolve().parent / "fixtures" / "adapters" / "echo.toml"
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
PROMPT = "\n\n❯ \n? for shortcuts\n"
LOGGED_OUT = "echo is not logged in\n\n❯ \n? for shortcuts\n"     # echo's own logout words
GARBAGE = 'Traceback (most recent call last):\n  {"meters": [oops'


def offline(home, sink):
    """The tick asks the public model boards and the host's browser over HTTP itself: every
    proxy names a loopback port nobody listens on, and only the sink is reached past them."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))
    near = sink.url.split("/")[2]
    home.env.update(no_proxy=near, NO_PROXY=near)


def state(home, name):
    return json.loads((home.path / ".agentkit" / "state" / name).read_text())


def title(home, seat):
    return home.tmux("show-options", "-v", "-t", f"={seat}:", "set-titles-string").out


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AnIdleSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        offline(cls.home, cls.sink)
        akconfig.write(cls.home, ["opus"])      # the audit off: a tick opens no seat of its own
        Seat(cls.home, "acme", screen="claude-prompt-pane.txt")
        cls.tick = cls.home.ak("watch", boxed=True)

    def test_a_seat_at_its_prompt_with_nothing_owed_reads_idle_with_no_reason(self):
        self.assertEqual(self.tick.code, 0, self.tick.err)
        record = state(self.home, "seat-acme.json")
        self.assertEqual((record["word"], record["state"], record["reason"]),
                         ("idle", "at_prompt", ""))

    def test_its_terminal_title_names_the_seat_and_its_word(self):
        self.assertEqual(title(self.home, "acme"), "acme · idle\n")

    def test_the_owner_is_not_paged(self):
        self.assertEqual(self.sink.requests, [])


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class FailingProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        offline(cls.home, cls.sink)
        cls.echo = fakeadapter.install(cls.home, echo="pass")["echo"]
        cls.echo.manifest.write_text(ECHO.read_text())
        for verb in ("usage", "login-end", "auth"):
            cls.echo.answer(verb, GARBAGE, 1)
        akconfig.write(cls.home, {"echo": {"harness": "echo", "model": "echo-1",
                                           "effort": "low"}})
        Seat(cls.home, "acme", model="echo", screen=PROMPT)
        Seat(cls.home, "beta", model="echo", screen=LOGGED_OUT)
        cls.done = [cls.home.ak("usage"), *(cls.home.ak("watch", boxed=True) for _ in "12")]

    def test_the_meters_the_login_s_end_and_the_seat_s_login_were_each_read(self):
        for done in self.done:
            self.assertEqual(done.code, 0, done.err)
        self.assertTrue(self.echo.calls("usage"))
        self.assertTrue(self.echo.calls("login-end"))
        self.assertIn(["seat"], [call["argv"] for call in self.echo.calls("auth")])

    def test_no_read_that_failed_pages_the_owner(self):
        self.assertEqual(self.sink.requests, [])

    def test_a_login_verb_that_cannot_answer_leaves_a_seat_under_logout_words_idle(self):
        record = state(self.home, "seat-beta.json")
        self.assertEqual((record["word"], record["reason"]), ("idle", ""))
        self.assertEqual(title(self.home, "beta"), "beta · idle\n")


if __name__ == "__main__":
    unittest.main()
