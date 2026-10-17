"""A question the seat kept back for its turn's end is answered by what its owner typed into
that turn after it.

A seat that asks while its turn runs keeps the question back and asks it when the turn ends.
Its owner reads it in the pane and often answers at once; a message typed while a turn runs
goes into that turn, and no prompt hook hears it.  The question used to be asked at the end
anyway, after its answer, and stood as `needs you` with its card out until the owner's next
prompt, hours later.  Now the first message of the owner's after the last question was kept
answers them, as his next prompt would: they are asked when the seat asked them, answered then,
and no card goes out.  A message from before the question answers nothing, and neither do
ak's own lines (`user_messages` leaves them out).

Offline: a sandbox HOME, a fake seat harness, Discord off.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, notify, orch, watch

SEAT = "fix-api"
QUESTION = "Which schema should acme use? The parser reads both; v2 drops the legacy fields."


class Harness:
    """A seat's harness, as notify sees it: one conversation and the owner's messages in it."""
    name = "claude"

    def __init__(self):
        self.said = []

    def conversation(self, record, cwd):
        return "c1"

    def user_messages(self, record, cwd, conversation, *, seat=None):
        return [{"at": at, "text": "words"} for at in self.said]


class AnswerMidTurn(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        self.harness, self.posts = Harness(), []
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off",
            "AK_RUN_ROLE": ""}))
        self.stack.enter_context(patch.object(orch, "seat_plugin", lambda record: self.harness))
        self.stack.enter_context(patch.object(notify, "close_needs", return_value=[]))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[
            {"name": SEAT, "attached": False}]))

    def asks_at(self, at):
        """The seat's own `ak notify needs`, during its turn."""
        with patch.object(watch.time, "time", return_value=at):
            self.assertEqual(notify.main(["needs", QUESTION]), 0)

    def turn_ends_at(self, at):
        with patch.object(watch.time, "time", return_value=at):
            watch.turn_ended(SEAT)
        with notify.session_lock(SEAT) as held, patch.object(notify.time, "time", return_value=at):
            self.assertTrue(notify.ask_kept(held, ended=True))

    def test_his_answer_typed_into_the_turn_answers_the_question_it_kept(self):
        self.asks_at(1000.0)
        self.harness.said = [900.0, 1060.0]     # 900: the prompt that began the turn
        self.turn_ends_at(1300.0)
        self.assertIsNone(notify.last(SEAT))    # nothing stands: no needs you, no card
        notice = notify.last(SEAT, include_seen=True)
        self.assertEqual((notice["text"], notice["time"], notice["answered_at"]),
                         (QUESTION, 1000.0, 1060.0))
        moments = history.owner(0, 2000)
        self.assertEqual([(kind, waited) for _, kind, waited in moments],
                         [("asked", None), ("answered", 60.0)])

    def test_a_question_standing_beside_it_is_answered_by_his_reply_after_both(self):
        self.asks_at(1000.0)
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "inbox"}), \
                patch.object(notify.time, "time", return_value=1100.0):
            self.assertEqual(notify.main(["needs", "--session", SEAT, "Merge acme#7?"]), 0)
        self.harness.said = [900.0, 1060.0, 1200.0]     # 1060 came before the second question
        self.turn_ends_at(1300.0)
        self.assertIsNone(notify.last(SEAT))
        self.assertEqual(notify.last(SEAT, include_seen=True)["answered_at"], 1200.0)

    def test_his_prompt_whose_words_answer_it_lets_go_of_the_stall_latch(self):
        self.asks_at(1000.0)
        with watch.state_lock():
            state = watch.load_state()
            state["stalls"][SEAT] = {"signature": "API Error", "since": 900.0, "told": 950.0}
            watch._write_state(state)
        with patch.object(watch.time, "time", return_value=1300.0):
            watch.turn_ended(SEAT)
        self.harness.said = [900.0, 1400.0]
        notify.answered(SEAT, 1400.0)
        self.assertIsNone(notify.last(SEAT))
        self.assertNotIn(SEAT, watch.load_state()["stalls"])

    def test_a_message_from_before_the_question_answers_nothing(self):
        self.asks_at(1000.0)
        self.harness.said = [900.0, 990.0]
        self.turn_ends_at(1300.0)
        notice = notify.last(SEAT)
        self.assertEqual((notice["text"], notice["time"]), (QUESTION, 1300.0))
        self.assertNotIn("answered_at", notice)

    def test_a_harness_that_reads_no_messages_asks_at_the_end_as_before(self):
        self.asks_at(1000.0)
        self.harness.user_messages = lambda *args, **kw: (_ for _ in ()).throw(OSError("gone"))
        self.turn_ends_at(1300.0)
        self.assertEqual(notify.last(SEAT)["time"], 1300.0)


if __name__ == "__main__":
    unittest.main()
