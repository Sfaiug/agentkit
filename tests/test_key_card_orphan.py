"""A card whose seat is gone is closed by the next `ak watch` pass, and never paged.

A card is the one page a seat's word may send.  Once neither tmux nor a saved record holds the
seat, nobody is left to answer it: the tick removes its card, and a page still owed to the
webhook for it is called off, so the owner is never sent to a seat that is not there.  A tmux
session by that name with no agent in it holds no seat either.  A seat tmux lost but whose
record is kept, and a live one, keep theirs.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, beside seats of tests/fixtures/akseat.py, paging
tests/fixtures/sink.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.sink import Sink
from fixtures import akconfig


def card(word, sent, ago=900):
    stamp = time.time() - ago
    return {"word": word, "since": stamp, "began": stamp, "episode": f"ep-{word}-{sent}",
            "sent": sent}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ATickClosesTheCardsOfGoneSeats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = cls.home = Home()
        cls.addClassCleanup(home.close)
        sink = cls.sink = Sink(home)
        cls.addClassCleanup(sink.close)
        akconfig.write(home, ["opus"])
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        # A page the webhook refused is owed, to be tried again, when its seat goes.
        sink.script(500)
        Seat(home, "fix-api")
        asked = home.ak("notify", "needs", "Which branch?", "--session", "fix-api")
        assert asked.code == 0, asked.err
        sink.wait(1)
        # before fix-api goes: a server left with no session exits, and a client that reaches
        # it on its way out fails with `server exited unexpectedly`
        stray = home.tmux("new-session", "-d", "-s", "stray", "sleep 600")
        assert stray.code == 0, stray.err
        assert home.tmux("kill-session", "-t", "=fix-api").code == 0
        (home.path / ".agentkit/state/session-fix-api.json").unlink()
        cls.write_card("gone", card("needs you", True))
        cls.write_card("lapsed", card("needs you", False))
        cls.write_card("stray", card("needs you", False))
        Seat(home, "beta", alive=False)
        cls.write_card("beta", card("needs you", True))
        Seat(home, "acme")
        cls.write_card("acme", card("needs you", True))
        cls.ticked = home.tick()

    @classmethod
    def write_card(cls, seat, data):
        cls.home.write(f".agentkit/state/card-{seat}.json", data)

    def has_card(self, seat):
        return (self.home.path / ".agentkit/state" / f"card-{seat}.json").exists()

    def test_the_tick_succeeds(self):
        self.assertEqual(self.ticked.code, 0, self.ticked.err)

    def test_a_card_whose_seat_is_neither_in_tmux_nor_on_record_is_removed(self):
        for seat in ("gone", "lapsed", "fix-api"):
            with self.subTest(seat):
                self.assertFalse(self.has_card(seat))

    def test_a_tmux_session_by_that_name_with_no_agent_in_it_holds_no_card(self):
        self.assertFalse(self.has_card("stray"))

    def test_a_page_still_owed_for_a_gone_seat_is_called_off_and_nothing_is_paged(self):
        outbox = self.home.path / ".agentkit/state/notification-outbox"
        event, = (json.loads(path.read_text()) for path in outbox.glob("*.json"))
        self.assertEqual((event["session"], event["status"]), ("fix-api", "disabled"))
        self.assertEqual(len(self.sink.requests), 1)    # only the one the webhook refused

    def test_a_seat_tmux_lost_with_its_record_kept_and_a_live_seat_keep_their_cards(self):
        for seat in ("beta", "acme"):
            with self.subTest(seat):
                self.assertTrue(self.has_card(seat))


if __name__ == "__main__":
    unittest.main()
