"""A worker token ending within three days pages the owner once a day; from two weeks out the ak
screen says when it ends, and the seat's word never does.

A worker token that runs out stops every headless turn of its harness, and only the owner can
make a new one, so they hear of it before it ends: the ak screen carries a line from two weeks
out, and within three days each tick pages them, at most once a local day, by the token's name
alone (`Needs you · claude worker token`), while every seat keeps its own word.  The token's
date is its file's: claude's lives a year from the day `~/.agentkit/secrets/claude_oauth_token`
was written, and a new file date is read at once.  The owner's day is the Home's zone, so a
zone where the date is another stands for another day.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, each tick in its box, with a seat from
akseat.py, the ak screen in a terminal of akterm.py and the pages at the webhook of sink.py.
"""

from datetime import datetime, timedelta, timezone
import socket
from pathlib import Path
import sys
import time
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from fixtures.sink import Sink

DAY = 86400
PAGE = "🙋 Needs you · claude worker token"
# Bound and never listening, so every connection to it is refused: a tick also reads the public
# model boards and the host's shared browser, and through this proxy it reaches neither, while
# its box keeps the loopback the sink listens on.
_REFUSER = socket.socket()
_REFUSER.bind(("127.0.0.1", 0))
REFUSED = f"http://127.0.0.1:{_REFUSER.getsockname()[1]}"


def tick(home):
    sink = urlsplit(home.env.get("AK_NOTIFY_SINK") or "").netloc
    proxies = {name: REFUSED for name in ("http_proxy", "https_proxy", "HTTP_PROXY",
                                         "HTTPS_PROXY")}
    done = home.tick(env={**proxies, "no_proxy": sink, "NO_PROXY": sink}, loopback=True)
    assert done.code == 0, done.out + done.err


def zone(hours):
    """The tz database's name for UTC+hours: its Etc zones count west of UTC."""
    return f"Etc/GMT{-hours:+d}"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class WorkerToken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(cls.home, ["opus"])
        Seat(cls.home, "acme")
        # midday where the Home is, so its ticks share a day; the other zone is an hour or
        # more from its own midnight, a day before or after
        cls.offset = 12 - time.gmtime().tm_hour
        cls.home.env["TZ"] = zone(cls.offset)
        cls.mtimes, cls.screens, cls.pages = {}, {}, {}
        for left in (15, 4, 2):
            # an hour over the days left, so a day's count holds while the test runs
            token = cls.home.write(".agentkit/secrets/claude_oauth_token", "acme-token\n",
                                   ago=(365 - left) * DAY - 3600)
            cls.mtimes[left] = token.stat().st_mtime
            cls.screens[left] = cls.screen()
            tick(cls.home)
            cls.pages[left] = cls.sink.pages()
        tick(cls.home)
        cls.same_day = cls.sink.pages()
        cls.word = cls.home.ak("orch", "why", "acme").out.splitlines()[:1]
        cls.home.env["TZ"] = zone(cls.offset + 13 if cls.offset <= 1 else cls.offset - 14)
        tick(cls.home)
        cls.next_day = cls.sink.pages()

    @classmethod
    def screen(cls):
        """The ak screen's rows once it is drawn, the person then leaving it."""
        term = Terminal(cls.home, size=(100, 40))
        shown = term.wait(lambda screen: "acme" in screen and "esc leave" in screen)
        term.keys("Escape")
        assert term.exit_code() == 0, term.screen()
        return [row.strip() for row in shown.splitlines()]

    def line(self, left):
        """What the ak screen says of a token `left` days from its end, in the Home's zone."""
        ends = datetime.fromtimestamp(self.mtimes[left] + 365 * DAY,
                                      timezone(timedelta(hours=self.offset)))
        return f"claude worker token expires {ends:%Y-%m-%d} (in {left} days)"

    def test_more_than_two_weeks_out_the_screen_says_nothing_and_no_one_is_paged(self):
        self.assertFalse([row for row in self.screens[15] if "worker token" in row],
                         self.screens[15])
        self.assertEqual(self.pages[15], [])

    def test_from_two_weeks_out_the_ak_screen_says_when_it_ends(self):
        for left in (4, 2):
            with self.subTest(left=left):
                self.assertIn(self.line(left), self.screens[left])

    def test_more_than_three_days_out_no_one_is_paged(self):
        self.assertEqual(self.pages[4], [])

    def test_within_three_days_the_owner_is_paged_once_that_day(self):
        self.assertEqual(self.pages[2], [PAGE])
        self.assertEqual(self.same_day, [PAGE])

    def test_the_next_day_the_owner_is_paged_again(self):
        self.assertEqual(self.next_day, [PAGE, PAGE])

    def test_the_seat_keeps_its_own_word(self):
        self.assertEqual(self.word, ["acme  idle"])


if __name__ == "__main__":
    unittest.main()
