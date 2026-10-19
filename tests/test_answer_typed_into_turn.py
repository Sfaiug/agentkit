"""What the owner types into a seat's turn after it asked answers its question.

A seat that asks while its turn runs keeps the question back and asks it when the turn ends.
Its owner reads it in the pane and often answers at once; a message typed while a turn runs
goes into that turn, and no prompt hook hears it.  The question used to stand as `needs you`,
its card out, until the owner's next prompt, hours later.  Now the tick, before its card pass,
answers a standing question whose seat's conversation holds a message of the owner's written
after the question was said, by the path their prompt takes (`notify.answered`): its waits, the
stall latch it lets go are their prompt's.  A message from
before the question, or before another question standing beside it, answers nothing, and
neither do ak's own lines (`user_messages` leaves them out).  A question still kept back waits
for the look that asks it.

Offline: a sandbox HOME, a fake seat harness, Discord off.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, notify, orch, watch

SEAT = "fix-api"
QUESTION = "Which schema should acme use? The parser reads both; v2 drops the legacy fields."
INBOX = "Merge acme#7? yes/no"


class Harness:
    """A seat's harness, as notify sees it: one conversation and the owner's messages in it."""
    name = "claude"

    def __init__(self):
        self.said = []

    def conversation(self, record, cwd):
        return "c1"

    def user_messages(self, record, cwd, conversation, *, seat=None):
        return [{"at": at, "text": "words"} for at in self.said]


class AnswerTypedIntoTurn(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        self.harness, self.logs = Harness(), []
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off",
            "AK_RUN_ROLE": ""}))
        self.stack.enter_context(patch.object(orch, "seat_plugin", lambda record, **_kw: self.harness))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[
            {"name": SEAT, "attached": False}]))

    def asks_at(self, at):
        """The seat's own `ak notify needs`, during its turn: kept back for its end."""
        with patch.object(watch.time, "time", return_value=at):
            self.assertEqual(notify.main(["needs", QUESTION]), 0)

    def turn_ends_at(self, at):
        """The turn ends, and a look finds it over and asks what it kept back."""
        with patch.object(watch.time, "time", return_value=at):
            watch.turn_ended(SEAT)
        with notify.session_lock(SEAT) as held:
            self.assertTrue(notify.ask_kept(held, ended=True))

    def tick_at(self, at):
        with patch.object(notify.time, "time", return_value=at), \
                patch.object(watch.time, "time", return_value=at):
            notify.answer_typed(log=self.logs.append)

    def stalled(self):
        with watch.state_lock():
            state = watch.load_state()
            state["stalls"][SEAT] = {"signature": "API Error", "since": 900.0, "told": 950.0}
            watch._write_state(state)

    def test_their_answer_typed_into_the_turn_answers_it_as_their_prompt_would(self):
        self.stalled()
        self.asks_at(1000.0)
        self.harness.said = [900.0, 1200.0]     # 900: the prompt that began the turn
        self.turn_ends_at(1300.0)
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)     # asked at the turn's end
        self.tick_at(1310.0)
        self.assertIsNone(notify.last(SEAT))    # answered: no needs you, and the card pass sends none
        notice = notify.last(SEAT, include_seen=True)
        self.assertEqual((notice["said_at"], notice["time"], notice["answered_at"]),
                         (1000.0, 1300.0, 1310.0))
        self.assertEqual([(kind, waited) for _, kind, waited in history.owner(0, 2000)],
                         [("asked", None), ("answered", 10.0)])
        self.assertEqual(watch.load_state()["stalls"], {})      # the latch it held is let go
        self.assertEqual(self.logs, [f"{SEAT}: its question was answered in the turn it was asked in"])

    def test_a_message_from_before_the_question_answers_nothing(self):
        self.asks_at(1000.0)
        self.harness.said = [900.0, 990.0]
        self.turn_ends_at(1300.0)
        self.tick_at(1310.0)
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)
        self.assertNotIn("answered_at", notify.last(SEAT))

    def test_a_message_before_a_question_standing_beside_it_answers_neither(self):
        self.asks_at(1000.0)
        with patch.object(notify.time, "time", return_value=1100.0), \
                patch.dict(os.environ, {"AGENTKIT_SESSION": "inbox"}):
            self.assertEqual(notify.main(["needs", "--session", SEAT, INBOX]), 0)
        self.harness.said = [1050.0]
        self.turn_ends_at(1300.0)
        self.assertEqual(notify.last(SEAT)["said_at"], 1100.0)
        self.tick_at(1310.0)
        self.assertIsNotNone(notify.last(SEAT))
        self.harness.said.append(1200.0)        # after both: it answers both
        self.tick_at(1320.0)
        self.assertIsNone(notify.last(SEAT))

    def test_a_question_asked_while_their_messages_are_read_still_stands(self):
        self.asks_at(1000.0)
        self.turn_ends_at(1100.0)
        second = "Ship the parser today? It needs the schema first."

        def read_messages(*args, **kw):
            with patch.object(notify.time, "time", return_value=1250.0):
                self.assertEqual(notify.main(["needs", second]), 0)
            return [{"at": 1200.0, "text": "Use v2."}]
        self.harness.user_messages = read_messages
        self.tick_at(1300.0)
        self.assertIn(second, notify.last(SEAT)["text"])
        self.assertNotIn("answered_at", notify.last(SEAT))
        self.assertEqual(self.logs, [])

    def test_a_question_still_kept_back_waits_for_the_look_that_asks_it(self):
        self.asks_at(1000.0)
        self.harness.said = [1200.0]
        self.tick_at(1250.0)                    # the turn still runs: nothing stands to answer
        self.assertEqual([q["text"] for q in watch.questions_kept(
            watch.seat_read(SEAT).get("unasked"))], [QUESTION])
        self.turn_ends_at(1300.0)
        self.tick_at(1310.0)
        self.assertIsNone(notify.last(SEAT))

    def test_a_harness_that_reads_no_messages_answers_nothing(self):
        self.asks_at(1000.0)
        self.harness.user_messages = lambda *args, **kw: (_ for _ in ()).throw(OSError("gone"))
        self.turn_ends_at(1300.0)
        self.tick_at(1310.0)
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)


if __name__ == "__main__":
    unittest.main()
