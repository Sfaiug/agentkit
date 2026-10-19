"""A seat cannot say its job is done while a question it asked its owner is open.

A seat asks and works on what does not wait on the answer.  Were its `ak notify done` to take
the question's place, as a seat's own word once did, the seat could decide the question for its
owner and call the job finished while he was away.  So a done is refused while the seat's own
question stands unanswered -- kept back for its turn's end, or asked -- and goes through once
his answer is on record.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, watch

SEAT = "fix-api"
QUESTION = "Which schema should acme use? The parser reads both; v2 drops the legacy fields."


class DoneWaitsForAnswer(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off",
            "AK_RUN_ROLE": ""}))
        self.posts = []

        def post(payload, files, message, receipt):
            self.posts.append(payload["content"])
            receipt.update(status="disabled", message_id="1", webhook="sink")
            return 0
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", return_value=[]))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[
            {"name": SEAT, "attached": False}]))

    def refused(self):
        with self.assertRaises(notify.Refused) as caught:
            notify.main(["done", "Shipped the schema move"])
        self.assertIn("your question to the owner is still open (Which schema should acme use?)",
                      str(caught.exception))
        self.assertNotEqual((notify.last(SEAT, include_seen=True) or {}).get("kind"), "done")

    def test_a_question_kept_for_the_turns_end_holds_the_done(self):
        self.assertEqual(notify.main(["needs", QUESTION]), 0)
        self.assertEqual(watch.seat_read(SEAT)["unasked"]["text"], QUESTION)
        self.refused()
        self.assertEqual(watch.seat_read(SEAT)["unasked"]["text"], QUESTION)

    def test_an_asked_question_holds_the_done_until_the_owner_answers(self):
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "inbox"}):
            self.assertEqual(notify.main(["needs", "--session", SEAT, QUESTION]), 0)
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)
        self.refused()
        notify.answered(SEAT, notify.last(SEAT)["time"] + 1)
        self.assertEqual(notify.main(["done", "Shipped the schema move"]), 0)
        self.assertEqual(notify.last(SEAT, include_seen=True)["kind"], "done")

    def test_a_question_kept_while_the_done_records_outranks_it(self):
        said = notify._said

        def asked_meanwhile(name, kind, *args, **kw):
            if kind == "done":      # past the gate: keeping a question takes no notice lock
                self.assertEqual(notify.main(["needs", QUESTION]), 0)
            return said(name, kind, *args, **kw)
        with patch.object(notify, "_said", side_effect=asked_meanwhile):
            self.assertEqual(notify.main(["done", "Shipped the schema move"]), 0)
        self.assertEqual(watch.seat_read(SEAT)["unasked"]["text"], QUESTION)
        self.assertNotEqual(watch.session_state(SEAT)["word"], "done")
        self.assertNotIn(f"Done · {SEAT}", self.posts)
        with self.assertRaises(notify.Refused):
            notify.main(["done", "Shipped the schema move"])

    def test_a_done_with_nothing_asked_goes_through(self):
        self.assertEqual(notify.main(["done", "Shipped the schema move"]), 0)
        self.assertEqual(notify.last(SEAT, include_seen=True)["kind"], "done")


if __name__ == "__main__":
    unittest.main()
