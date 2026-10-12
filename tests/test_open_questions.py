"""A seat keeps every question it asked open until its owner answers.

A seat asks, works on, and may ask again before its owner is back.  A newer question used to
take the earlier one's place, so the seat's line showed only the last, and the one before it was
lost to the owner while the seat still waited on its answer.  Now a question asked while others
stand unanswered -- kept back for the same turn's end, or asked -- is asked beside them, in the
order asked, each once: the line reads them all, the card stays the one card, and the owner's
one prompt answers them.  After his answer a new question stands alone.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, watch

SEAT = "fix-api"
FIRST = "Which schema should acme use? The parser reads both; v2 drops the legacy fields."
SECOND = "Ship the parser today? It needs the schema first."


class OpenQuestions(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        self.posts = []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off",
            "AK_RUN_ROLE": ""}))
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", return_value=[]))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[
            {"name": SEAT, "attached": False}]))

    def asks(self, question):
        """The seat's own `ak notify needs`, during its turn."""
        self.assertEqual(notify.main(["needs", question]), 0)

    def turn_ends(self):
        """The turn the seat asked in ends, and what it kept back is asked."""
        watch.turn_ended(SEAT)
        with notify.session_lock(SEAT) as held:
            self.assertTrue(notify.ask_kept(held, ended=True))

    def asked_for_it(self, question):
        """Asked for the seat from outside it: at once, as the inbox is asked."""
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "inbox"}):
            self.assertEqual(notify.main(["needs", "--session", SEAT, question]), 0)

    def test_a_turn_that_asks_twice_asks_both_when_it_ends(self):
        self.asks(FIRST)
        self.asks(SECOND)
        self.assertEqual(watch.seat_read(SEAT)["unasked"]["text"], FIRST + " Also: " + SECOND)
        self.turn_ends()
        self.assertEqual(notify.last(SEAT)["text"], FIRST + " Also: " + SECOND)

    def test_a_question_asked_while_one_stands_is_asked_beside_it(self):
        self.asked_for_it(FIRST)
        self.asks(SECOND)
        self.assertNotIsInstance(watch.seat_read(SEAT).get("unasked"), dict)
        self.assertEqual(notify.last(SEAT)["text"], FIRST + " Also: " + SECOND)
        self.assertEqual(self.posts, ["Needs you · " + SEAT])     # still the one card

    def test_a_question_kept_back_is_asked_beside_one_asked_at_once(self):
        self.asks(FIRST)                    # kept back for this turn's end
        self.asked_for_it("Merge acme#7? yes/no")
        self.asks(SECOND)                   # asked at once: the owner is asked already
        self.assertEqual(notify.last(SEAT)["text"],
                         "Merge acme#7? yes/no Also: " + FIRST + " Also: " + SECOND)
        self.assertNotIsInstance(watch.seat_read(SEAT).get("unasked"), dict)

    def test_the_same_question_twice_is_asked_once_as_last_asked(self):
        again = "  which SCHEMA should acme use?\nThe parser reads both; v2 drops the legacy fields."
        self.asked_for_it(FIRST)
        self.asked_for_it(SECOND)
        self.asks(again)
        self.assertEqual(notify.last(SEAT)["text"], SECOND + " Also: " + again.strip())

    def test_a_question_inside_another_is_one_of_its_own(self):
        first = "Ship the acme parser? Its README quotes Use v1? as an example."
        self.asks(first)
        self.asks("Use v1?")
        self.turn_ends()
        self.assertEqual(notify.last(SEAT)["text"], first + " Also: Use v1?")

    def test_one_kept_and_asked_already_is_asked_once(self):
        self.asks(FIRST)
        self.asked_for_it(FIRST)
        self.asks(SECOND)
        self.assertEqual(notify.last(SEAT)["text"], FIRST + " Also: " + SECOND)

    def test_after_his_answer_a_new_question_stands_alone(self):
        self.asked_for_it(FIRST)
        notify.answered(SEAT, notify.last(SEAT)["time"] + 1)
        self.asks(SECOND)
        self.turn_ends()
        self.assertEqual(notify.last(SEAT)["text"], SECOND)

    def test_one_kept_before_his_prompt_is_recorded_waits_for_its_own_turn(self):
        """His prompt is recorded in the background: the seat's next turn may keep another
        first, which his prompt never saw."""
        self.asks(FIRST)
        watch.turn_ended(SEAT)
        self.asks(SECOND)
        notify.answered(SEAT, 10001)
        self.assertIsNone(notify.last(SEAT))
        self.turn_ends()
        self.assertEqual(notify.last(SEAT)["text"], SECOND)

    def test_his_prompt_recorded_late_answers_only_those_asked_before_it(self):
        self.asked_for_it(FIRST)
        with patch.object(notify.time, "time", return_value=10002):
            self.asks(SECOND)
        notify.answered(SEAT, 10001)
        self.assertEqual(notify.last(SEAT)["text"], SECOND)

    def test_a_later_asking_keeps_its_time_beside_an_older_kept_one(self):
        self.asks(FIRST)
        watch.turn_ended(SEAT)
        with patch.object(notify.time, "time", return_value=10002):
            self.asked_for_it(FIRST)
            self.asks(SECOND)
        notify.answered(SEAT, 10001)        # his prompt came before the later asking
        self.assertEqual(notify.last(SEAT)["text"], FIRST + " Also: " + SECOND)

    def test_a_stop_while_its_kept_question_is_asked_leaves_nothing_kept(self):
        self.asks(FIRST)
        self.asked_for_it("Merge acme#7? yes/no")
        said = notify._said

        def stopped(*args, **kwargs):
            previous = said(*args, **kwargs)
            watch.turn_ended(SEAT)
            return previous
        with patch.object(notify, "_said", side_effect=stopped):
            self.asks(SECOND)
        self.assertIsNone(watch.seat_read(SEAT).get("unasked"))

    def test_his_prompt_answers_one_the_old_install_kept_for_an_ended_turn(self):
        watch.seat_write(SEAT, unasked={"text": FIRST, "at": 9999.0, "ended": 10000.0})
        notify.answered(SEAT, 10001)
        self.assertIsNone(watch.seat_read(SEAT).get("unasked"))
        self.assertIsNone(notify.last(SEAT))


if __name__ == "__main__":
    unittest.main()
