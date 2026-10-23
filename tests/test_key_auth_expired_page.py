"""An expired harness login reads `needs you`, pages the owner once, and clears once it is back.

A seat whose harness can no longer log in waits for the one person who can log it in again, so
the tick asks the harness's `auth` verb about the seat's own login when the screen shows that
harness's logout words, and on its no keeps a stall of kind `auth`, the seat's notice and its
reason, each saying the harness's own remedy out of its manifest, and pages the owner with only
the word and the seat, once however many ticks it lasts.  When the verb passes again the stall
goes, the notice is marked seen, the seat reads its own word again and nothing more is paged.
Black-box: the program `AK_BIN` names runs `ak watch` from outside through
tests/fixtures/akbin.py, before a seat of tests/fixtures/akseat.py, on the echo harness of
tests/fixtures/adapters behind tests/fixtures/fakeadapter.py, paging tests/fixtures/sink.py.
"""

import json
import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

ECHO = Path(__file__).resolve().parent / "fixtures" / "adapters" / "echo.toml"
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
LOGGED_OUT = "echo is not logged in\n\n❯ \n? for shortcuts\n"     # echo's own logout words
PROMPT = "\n\n❯ \n? for shortcuts\n"
NOTICE = ("acme (Echo) needs login: open the host, press this session's number, and nothing: "
          "the echo fixture has no login.")
REASON = "echo login expired: open it and nothing: the echo fixture has no login"


def offline(home, sink):
    """The tick asks the public model boards and the host's browser over HTTP itself: every
    proxy names a loopback port nobody listens on, and only the sink is reached past them."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))
    near = sink.url.split("/")[2]
    home.env.update(no_proxy=near, NO_PROXY=near)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AuthExpired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        offline(home, cls.sink)
        cls.echo = fakeadapter.install(home, echo="pass")["echo"]
        cls.echo.manifest.write_text(ECHO.read_text())
        cls.echo.answer("auth", "echo token expired", 1)
        akconfig.write(home, {"echo": {"harness": "echo", "model": "echo-1", "effort": "low"}})
        seat = Seat(home, "acme", model="echo", screen=LOGGED_OUT)
        cls.ticks = [home.ak("watch")]
        cls.paged = list(cls.sink.wait(1))
        cls.ticks.append(home.ak("watch"))
        cls.out = cls.read()
        cls.echo.answer("auth", "token in ~/.echo", 0)
        seat.show(PROMPT)
        cls.ticks.append(home.ak("watch"))
        cls.back = cls.read()

    @classmethod
    def read(cls):
        """The tick's state, the seat's notice and record and its title, and what was paged."""
        kept = cls.home.path / ".agentkit" / "state"
        found = {name: json.loads((kept / f"{name}.json").read_text())
                 for name in ("watch", "notify-acme", "seat-acme")}
        found["title"] = cls.home.tmux("show-options", "-v", "-t", "=acme:",
                                       "set-titles-string").out
        found["pages"] = cls.sink.pages()
        return found

    def test_every_tick_succeeds(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.err)

    def test_the_tick_asks_the_seat_s_own_login(self):
        self.assertIn(["seat"], [call["argv"] for call in self.echo.calls("auth")])

    def test_an_expired_login_is_a_stall_of_kind_auth_saying_the_harness_s_remedy(self):
        stall = self.out["watch"]["stalls"]["acme"]
        self.assertEqual((stall["kind"], stall["harness"], stall["notice"]),
                         ("auth", "echo", NOTICE))
        self.assertIs(self.out["watch"]["auth_out"]["echo"]["ok"], False)

    def test_the_seat_reads_needs_you_with_the_login_as_its_reason(self):
        record = self.out["seat-acme"]
        self.assertEqual((record["word"], record["reason"]), ("needs you", REASON))
        self.assertEqual(self.out["title"], "acme · needs you\n")

    def test_the_seat_s_notice_is_the_login_s(self):
        notice = self.out["notify-acme"]
        self.assertEqual((notice["kind"], notice["text"]), ("needs", NOTICE))
        self.assertTrue(notice["source"].startswith("auth:acme:echo:"), notice["source"])

    def test_the_owner_is_paged_once_over_two_ticks_with_only_the_word_and_the_seat(self):
        page, = self.paged
        self.assertEqual(page.method, "POST")
        self.assertEqual(self.out["pages"], ["🙋 Needs you · acme"])

    def test_a_login_that_passes_again_clears_the_stall_and_the_seat_reads_idle(self):
        self.assertEqual(self.back["watch"]["stalls"], {})
        self.assertIs(self.back["watch"]["auth_out"]["echo"]["ok"], True)
        self.assertEqual(self.back["seat-acme"]["word"], "idle")
        self.assertEqual(self.back["title"], "acme · idle\n")
        self.assertIs(self.back["notify-acme"]["seen"], True)

    def test_clearing_the_login_pages_nothing_more(self):
        self.assertEqual(self.back["pages"], ["🙋 Needs you · acme"])


if __name__ == "__main__":
    unittest.main()
