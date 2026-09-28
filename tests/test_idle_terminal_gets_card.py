"""Only client input during a needs-you episode keeps its card quiet."""

import json
import os
from unittest.mock import patch
import unittest

from test_v4n import Sandbox
from agentkit import config, notify, orch

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
        self.clients = []
        self.posts, self.edits = [], []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(notify, "session_number", return_value=1))
        self.stack.enter_context(patch.object(notify, "post", side_effect=self.post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=self.close))

    def tmux(self, *args, socket=None):
        self.assertEqual(socket, orch.seat_socket(self.seat))
        self.assertEqual(args[:2], ("list-clients", "-t"))
        target = args[2].removeprefix("=")
        fmt = args[4] if args[3:4] == ("-F",) else "#{session_name} (focused)"
        return 0, "\n".join(fmt.replace("#{session_name}", name)
                            .replace("#{client_activity}", str(activity))
                            .replace("#{client_flags}", "focused")
                            for name, activity in self.clients if name == target)

    def post(self, payload, files, message, receipt):
        self.posts.append(payload["embeds"][0]["title"])
        receipt.update(status="delivered", message_id=str(len(self.posts)), webhook="sink")
        return 0

    def close(self, previous, status):
        self.edits.extend((card["message_id"], status)
                          for card in previous.get("open_needs", []))
        return []

    def tick(self, elapsed=0, since=NOW, word="needs you"):
        answer = {"word": word, "since": since, "reason": "Choose a branch?"}
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
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"])
        self.assertEqual(self.edits, [])
        self.assertNotIn("closed", self.card())

    def test_input_during_the_wait_retires_the_episode_without_a_card(self):
        self.clients = [(SEAT, int(NOW) - 600)]
        self.tick()
        self.clients.append((SEAT, int(NOW) + 1))
        self.tick(1)
        self.assertEqual(self.card()["closed"], "Answered")
        self.tick(notify.CARD_WAIT)
        self.clients = []
        self.tick(300)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.edits, [])

    def test_input_after_delivery_closes_the_sent_card_as_answered_once(self):
        self.clients = [(SEAT, int(NOW) - 600)]
        self.tick(notify.CARD_WAIT)
        self.clients.append((SEAT, int(NOW) + 61))
        # Later state readings do not move the stored episode's start.
        self.tick(120, since=NOW + 100)
        self.tick(180)
        self.clients = []
        self.tick(300)
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"])
        self.assertEqual(self.edits, [("1", "Answered")])
        self.assertEqual(self.card()["closed"], "Answered")

    def test_no_attached_client_keeps_the_wait_delivery_and_answer(self):
        self.tick()
        self.tick(notify.CARD_WAIT - 1)
        self.assertEqual(self.posts, [])
        self.tick(notify.CARD_WAIT)
        self.tick(120)
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"])
        self.tick(180, since=NOW + 180, word="working")
        self.assertEqual(self.edits, [("1", "Answered")])

    def test_input_from_the_previous_episode_does_not_hide_a_new_question(self):
        self.clients = [(SEAT, int(NOW) + 1)]
        self.tick(1)
        self.tick(10, since=NOW + 10, word="working")
        self.tick(20, since=NOW + 20)
        self.tick(20 + notify.CARD_WAIT, since=NOW + 20)
        self.tick(300, since=NOW + 20)
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"])


if __name__ == "__main__":
    unittest.main()
