"""The owner in a seat is never paged for its question: a client in the seat holds its card,
and once he has left it goes out a minute after he left or last typed, whichever is later.
His keys hold back any card not out yet; only a question waits for him to leave.

Offline: a fake seat listing, a fake tmux answering `display-message`, and a fake sender.
"""

import json
import os
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, watch

NOW = 1_800_000_000.5
SEAT = "fix-api"
QUESTION = "Choose a branch?"


class OwnerInSeatNotPaged(Sandbox):
    def setUp(self):
        super().setUp()
        # `ak notify needs --session` is run from outside the seat
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_NOTIFY_SINK": "off", "AGENTKIT_SESSION": ""}))
        self.stack.enter_context(patch.object(notify.time, "time", return_value=NOW))
        self.typed = []
        self.clients = []
        self.posts = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(notify, "post", side_effect=self.post))

    @property
    def clients(self):
        """The clients on the server now, each (session, its newest key)."""
        return self._clients

    @clients.setter
    def clients(self, clients):
        # a client that leaves takes its own activity with it, never its session's
        self.typed.extend(getattr(self, "_clients", []))
        self._clients = clients

    @property
    def seat(self):
        """The seat as the listing reads it: `attached` is tmux's own `session_attached`."""
        return {"name": SEAT, "legacy": False,
                "attached": any(name == SEAT for name, _ in self.clients)}

    def tmux(self, *args, socket=None, **_kw):
        """`session_activity`: the newest key any client sent the session, gone or not."""
        self.assertEqual(socket, orch.seat_socket(self.seat))
        self.assertEqual(args, ("display-message", "-p", "-t", f"={SEAT}:",
                                "#{session_activity}"))
        return 0, str(max((activity for name, activity in self.typed + self.clients
                           if name == SEAT), default=0))

    def post(self, payload, files, message, receipt):
        self.posts.append(payload["content"])
        receipt.update(status="delivered", message_id=str(len(self.posts)), webhook="sink")
        return 0

    def answer(self, since=NOW, word="needs you", reason=QUESTION):
        return {"word": word, "since": since, "reason": reason,
                **({"question": True} if reason == QUESTION else {})}

    def tick(self, elapsed=0, **answer):
        answer = self.answer(**answer)
        with patch.object(watch, "session_state", return_value=answer):
            self.assertEqual(notify.transition(SEAT, answer, now=NOW + elapsed,
                                               seat=self.seat), 0)

    def ask(self):
        """`ak notify needs QUESTION --session fix-api`, at NOW."""
        with patch.object(watch, "session_state", return_value=self.answer()):
            self.assertEqual(notify.shaped("needs", QUESTION, session=SEAT), 0)

    def test_the_owner_in_the_seat_is_never_paged_however_long_he_is_silent(self):
        self.clients = [(SEAT, int(NOW) - 600), ("other-seat", int(NOW) + 30)]
        for elapsed in (0, notify.CARD_WAIT, 600, 3600):
            self.tick(elapsed)
        self.assertEqual(self.posts, [])
        self.clients = [("other-seat", int(NOW) + 30)]
        self.tick(3700)
        self.tick(3700 + notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(3700 + notify.CARD_WAIT)
        self.tick(3700 + 300)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_ak_notify_needs_waits_while_he_is_in_the_seat(self):
        self.clients = [(SEAT, int(NOW) - 600)]
        self.ask()
        self.tick(notify.CARD_WAIT)
        self.tick(600)
        self.assertEqual(self.posts, [])
        self.clients = []
        self.tick(700)
        self.tick(700 + notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(700 + notify.CARD_WAIT)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_ak_notify_needs_pages_at_once_where_nobody_has_been_for_a_minute(self):
        self.typed = [(SEAT, int(NOW) - notify.CARD_WAIT)]
        self.ask()
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_ak_notify_needs_waits_a_minute_from_his_last_key(self):
        # he typed and left the seat just before it asked: no tick saw him
        self.clients = [(SEAT, int(NOW) - 10)]
        self.clients = []
        self.ask()
        self.tick(notify.CARD_WAIT - 11)
        self.assertEqual(self.posts, [])
        self.tick(notify.CARD_WAIT)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_a_login_or_a_failure_is_sent_while_he_is_in_the_seat(self):
        self.clients = [(SEAT, int(NOW) - 600)]
        self.tick(reason="Claude login expired: run `/login`")
        self.tick(notify.CARD_WAIT - 1, reason="Claude login expired: run `/login`")
        self.assertEqual(self.posts, [])
        self.tick(notify.CARD_WAIT, reason="Claude login expired: run `/login`")
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_the_minute_counts_from_the_first_look_that_finds_him_gone(self):
        # tmux keeps no time he left: he may have stayed until that look
        self.clients = [(SEAT, int(NOW) - 600)]
        self.tick()
        self.clients = [(SEAT, int(NOW) + 50)]
        self.clients = []
        self.tick(notify.CARD_WAIT)
        self.tick(2 * notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(2 * notify.CARD_WAIT)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_his_last_key_holds_the_card_though_he_left_between_two_ticks(self):
        # no tick saw him: he typed and left the seat, or went to another, in between
        for departed in ([], [("other-seat", int(NOW) + 51)]):
            with self.subTest(departed=departed):
                config.card_path(SEAT).unlink(missing_ok=True)
                self.posts.clear()
                self.clients = []
                self.tick()
                self.clients = [(SEAT, int(NOW) + 50)]
                self.clients = departed
                self.tick(notify.CARD_WAIT)
                self.tick(50 + notify.CARD_WAIT - 1)
                self.assertEqual(self.posts, [])
                self.tick(50 + notify.CARD_WAIT)
                self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_input_after_delivery_leaves_the_sent_card_as_it_went(self):
        """A card that is out stays as it went (tests/test_card_agrees_with_the_seat.py): his
        keys there are him looking, and the word changing sends nothing more."""
        self.tick(notify.CARD_WAIT)
        self.clients = [(SEAT, int(NOW) + 61)]
        # Later state readings do not move the stored episode's start.
        self.tick(120, since=NOW + 100)
        self.tick(180)
        self.clients = []
        self.tick(300, since=NOW + 300, word="working")
        self.tick(360, since=NOW + 300, word="working")
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_no_attached_client_keeps_the_wait_delivery_and_answer(self):
        self.tick()
        self.tick(notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(notify.CARD_WAIT)
        self.tick(120)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])
        self.tick(180, since=NOW + 180, word="working")

    def test_input_from_the_previous_episode_does_not_hide_a_new_question(self):
        self.clients = [(SEAT, int(NOW) + 1)]
        self.tick(1)
        self.tick(10, since=NOW + 10, word="working")
        self.clients = []
        self.tick(20, since=NOW + 20)
        self.tick(20 + notify.CARD_WAIT, since=NOW + 20)
        self.tick(300, since=NOW + 20)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])


if __name__ == "__main__":
    unittest.main()
