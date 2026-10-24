"""A page pings the owner `AGENTKIT_DISCORD_USER_ID` names, and allows that mention alone.

The owner hears a page because it mentions them: that mention is all a page carries beside its
word and its seat, and the only one Discord may act on, so whatever a seat is called nobody
else is pinged.  The id in the environment outranks the one-line secrets file, whose own
mention tests/test_key_notify_needs_card.py pins, and it holds alike for a seat's own `ak
notify needs` and for the page the tick sends when a question has stood.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its tick in the box
`home.tick()` builds, beside seats of tests/fixtures/akseat.py, paging tests/fixtures/sink.py.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.sink import Sink


def card(seat, owner):
    """The whole body of a page about `seat` that pings `owner`."""
    return {"username": "agentkit", "content": f"🙋 Needs you · {seat} <@{owner}>",
            "allowed_mentions": {"users": [owner]}}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatAsks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        Seat(cls.home, "fix-api")
        Seat(cls.home, "fix-web")

    def paged(self, seat):
        """The one page `ak notify needs` sent for `seat`, the owner named in the environment."""
        before = len(self.sink.requests)
        done = self.home.ak("notify", "needs", "Which branch?", "--session", seat,
                            env={"AGENTKIT_DISCORD_USER_ID": "1234"})
        self.assertEqual(done.code, 0, done.err)
        page, = self.sink.wait(before + 1)[before:]
        return page

    def test_the_page_mentions_the_owner_named_in_the_environment_and_allows_only_them(self):
        page = self.paged("fix-api")
        self.assertEqual((page.method, page.path), ("POST", "/hook"))
        self.assertEqual(page.json, card("fix-api", "1234"))

    def test_the_environment_outranks_the_secrets_file(self):
        secret = self.home.write(".agentkit/secrets/discord_user_id", "42\n")
        self.addCleanup(secret.unlink)
        self.assertEqual(self.paged("fix-web").json, card("fix-web", "1234"))


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class TheTickPages(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        akconfig.write(self.home, ["opus"])     # the audit off: a tick opens no seat of its own

    def test_its_page_mentions_the_owner_named_in_the_environment_and_allows_only_them(self):
        # A seat that closed on its own with its question standing, the card a tick five minutes
        # ago held back: nobody is in it, so its minute has long passed.  A live seat's minute
        # counts from its tmux session's last activity, which no test can date back.  Its
        # conversation is not its own, so no tick reopens it to ask again.
        Seat(self.home, "acme", alive=False, record={"id_source": None})
        now = time.time()
        self.home.write(".agentkit/state/notify-acme.json",
                        {"session": "acme", "kind": "needs",
                         "text": "Which database should the app use?", "time": now - 300})
        self.home.write(".agentkit/state/card-acme.json",
                        {"word": "needs you", "since": now - 300, "began": now - 300,
                         "episode": "e" * 32, "sent": False})
        done = self.home.tick(env={"AGENTKIT_DISCORD_USER_ID": "123456789"})
        self.assertEqual(done.code, 0, done.err)
        page, = self.sink.wait(1)
        self.assertEqual((page.method, page.path), ("POST", "/hook"))
        self.assertEqual(page.json, card("acme", "123456789"))


if __name__ == "__main__":
    unittest.main()
