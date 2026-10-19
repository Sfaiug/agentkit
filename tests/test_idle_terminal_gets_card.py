"""Client input in a needs-you seat holds its card back only while he is there, and only
until the card is out."""

import json
import os
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, watch

NOW = 1_800_000_000.5
SEAT = "fix-api"


class IdleTerminalGetsCard(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_NOTIFY_SINK": "off", "AGENTKIT_SESSION": SEAT}))
        self.stack.enter_context(patch.object(notify.time, "time", return_value=NOW))
        self.seat = {"name": SEAT, "legacy": False}
        self.typed = []
        self.clients = []
        self.posts, self.edits = [], []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(notify, "post", side_effect=self.post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=self.close))

    @property
    def clients(self):
        """The clients on the server now, each (session, its newest key)."""
        return self._clients

    @clients.setter
    def clients(self, clients):
        # a client that leaves takes its own activity with it, never its session's
        self.typed.extend(getattr(self, "_clients", []))
        self._clients = clients

    def tmux(self, *args, socket=None, **_kw):
        """tmux's `session_activity`: the newest key any client sent the session, gone or not."""
        self.assertEqual(socket, orch.seat_socket(self.seat))
        self.assertEqual(args, ("display-message", "-p", "-t", f"={SEAT}:",
                                "#{session_activity}"))
        return 0, str(max((activity for name, activity in self.typed + self.clients
                           if name == SEAT), default=0))

    def post(self, payload, files, message, receipt):
        self.posts.append(payload["content"])
        receipt.update(status="delivered", message_id=str(len(self.posts)), webhook="sink")
        return 0

    def close(self, previous, status):
        self.edits.extend((card["message_id"], status)
                          for card in previous.get("open_needs", []))
        return []

    def tick(self, elapsed=0, since=NOW, word="needs you"):
        answer = {"word": word, "since": since, "reason": "Choose a branch?"}
        with patch.object(watch, "session_state", return_value=answer):
            self.assertEqual(notify.transition(SEAT, answer, now=NOW + elapsed,
                                               seat=self.seat), 0)

    def card(self):
        return json.loads(config.card_path(SEAT).read_text())

    def test_idle_attached_client_gets_exactly_one_card_after_the_wait(self):
        # Even input in the same second, but before the question, is not an answer.
        self.clients = [(SEAT, int(NOW)), ("other-seat", int(NOW) + 30)]
        self.tick()
        self.assertNotIn("closed", self.card())
        self.tick(notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(notify.CARD_WAIT)
        self.tick(120)
        self.tick(300)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])
        self.assertEqual(self.edits, [])
        self.assertNotIn("closed", self.card())

    def test_a_glance_holds_the_card_only_until_he_has_left_the_seat_a_minute(self):
        # a seat works on with its question standing: looking at it answers nothing
        self.clients = [(SEAT, int(NOW) - 600)]
        self.tick()
        self.clients = [(SEAT, int(NOW) + 50)]
        self.tick(notify.CARD_WAIT)
        self.tick(50 + notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(50 + notify.CARD_WAIT)
        self.tick(300)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])
        self.assertEqual(self.edits, [])

    def test_his_last_key_holds_the_card_though_he_left_between_two_ticks(self):
        # no tick saw the key: he typed and left the seat, or went to another, in between
        for departed in ([], [("other-seat", int(NOW) + 51)]):
            with self.subTest(departed=departed):
                config.card_path(SEAT).unlink(missing_ok=True)
                self.posts.clear()
                self.clients = [(SEAT, int(NOW) - 600)]
                self.tick()
                self.clients = [(SEAT, int(NOW) + 50)]
                self.clients = departed
                self.tick(notify.CARD_WAIT)
                self.tick(50 + notify.CARD_WAIT - 1)
                self.assertEqual(self.posts, [])
                self.tick(50 + notify.CARD_WAIT)
                self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_his_last_key_holds_the_card_after_he_leaves_the_seat(self):
        # a client that detaches or switches to another seat takes its own activity with it
        for clients in ([], [("other-seat", int(NOW) + 61)]):
            with self.subTest(clients=clients):
                config.card_path(SEAT).unlink(missing_ok=True)
                self.posts.clear()
                self.clients = [(SEAT, int(NOW) + 50)]
                self.tick(notify.CARD_WAIT)
                self.clients = clients
                self.tick(50 + notify.CARD_WAIT - 1)
                self.assertEqual(self.posts, [])
                self.tick(50 + notify.CARD_WAIT)
                self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])

    def test_input_after_delivery_leaves_the_sent_card_until_the_seat_needs_him_no_more(self):
        """A card that is out says what its seat says (tests/test_card_agrees_with_the_seat.py):
        his keys there are him looking, and the word changing is what closes it, once."""
        self.clients = [(SEAT, int(NOW) - 600)]
        self.tick(notify.CARD_WAIT)
        self.clients.append((SEAT, int(NOW) + 61))
        # Later state readings do not move the stored episode's start.
        self.tick(120, since=NOW + 100)
        self.tick(180)
        self.assertEqual(self.edits, [])
        self.assertNotIn("closed", self.card())
        self.clients = []
        self.tick(300, since=NOW + 300, word="working")
        self.tick(360, since=NOW + 300, word="working")
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])
        self.assertEqual(self.edits, [("1", "Answered")])

    def test_no_attached_client_keeps_the_wait_delivery_and_answer(self):
        self.tick()
        self.tick(notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(notify.CARD_WAIT)
        self.tick(120)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])
        self.tick(180, since=NOW + 180, word="working")
        self.assertEqual(self.edits, [("1", "Answered")])

    def test_input_from_the_previous_episode_does_not_hide_a_new_question(self):
        self.clients = [(SEAT, int(NOW) + 1)]
        self.tick(1)
        self.tick(10, since=NOW + 10, word="working")
        self.tick(20, since=NOW + 20)
        self.tick(20 + notify.CARD_WAIT, since=NOW + 20)
        self.tick(300, since=NOW + 20)
        self.assertEqual(self.posts, [f"🙋 Needs you · {SEAT}"])


if __name__ == "__main__":
    unittest.main()
