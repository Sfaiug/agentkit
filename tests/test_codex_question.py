"""A Codex seat's own question tool asks its owner through ak.

Codex 0.160's newer models ask with `request_user_input_async`, which waits for nobody: the model
hears `accepted` and works on, and Codex drops the question unanswered -- telling neither the
model nor ak -- when anything is sent into the seat or the turn ends.  So the seat's PreToolUse
hook asks it through ak, as the seat's own `ak notify needs` does: kept back for its turn's end,
then `needs you` and a card until the owner answers.  The call is refused with what became of the
question, so Codex holds no question of its own to drop, and with the question itself, which is
how the owner reads it in the seat: Codex draws a refusal's reason there.
"""

import io
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, notify, stop, watch
from agentkit.harness import codex

SEAT = "fix-api"
TITLE = "Which schema should acme use? The parser reads both; v2 drops the legacy fields."
CALL = {"hook_event_name": "PreToolUse", "tool_name": "request_user_input_async",
        "tool_input": {"questions": [{"title": TITLE, "options": ["Keep v1", "Move to v2"]}]},
        "tool_use_id": "call_1"}


class CodexQuestion(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "astra", ["astra"], {"cwd": str(self.root)})
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off",
            "AK_RUN_ROLE": ""}))

    def hook(self, event):
        """The seat's hook as Codex runs it: the event on stdin, its answer on stdout."""
        out = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(event))), \
                patch.object(sys, "stdout", out):
            self.assertEqual(codex.main(["ask"]), 0)
        return json.loads(out.getvalue()) if out.getvalue() else None

    def kept(self):
        kept = watch.seat_read(SEAT).get("unasked")
        return kept["text"] if isinstance(kept, dict) else None

    def test_the_question_is_aks_and_the_call_is_refused(self):
        answer = self.hook(CALL)
        self.assertEqual(answer["decision"], "block")
        self.assertTrue(answer["reason"].startswith("ak asks the owner this for you"), answer)
        self.assertIn(": " + TITLE + " Options: 1. Keep v1 · 2. Move to v2 Their answer",
                      answer["reason"])
        # Codex closes the reason with a period of its own
        self.assertFalse(answer["reason"].endswith("."))
        self.assertEqual(self.kept(), TITLE + " Options: 1. Keep v1 · 2. Move to v2")

    def test_a_question_ak_refuses_goes_back_to_the_model(self):
        late = {"title": "Two pages, Status and Analytics, with People one click away. " * 2
                         + "Does this feel right?"}
        answer = self.hook(dict(CALL, tool_input={"questions": [late]}))
        self.assertEqual(answer["decision"], "block")
        self.assertTrue(answer["reason"].startswith(
            "ak did not ask the owner this: put the question first"), answer)
        self.assertIsNone(self.kept())

    def test_a_seat_whose_plan_is_done_asks_nothing_until_the_owner_writes_again(self):
        plan = config.plan_path(SEAT)
        plan.write_text("- [x] the parser parses · check: `true` · acme · written "
                        "2026-10-09 12:00 · done 0123456789ab\n")
        done = time.time() - 600
        os.utime(plan, (done, done))
        refused = {"decision": "block", "reason": stop.DONE_ASKING.rstrip(".")}
        with patch.object(notify, "owner_said", return_value=[done - 3600]):
            # its Plan-mode dialog too, which then never reads as the seat asking
            for tool in ("request_user_input_async", "request_user_input"):
                self.assertEqual(self.hook(dict(CALL, tool_name=tool)), refused, tool)
            self.assertIsNone(self.kept())
            self.assertNotEqual(watch.hook_state("codex", watch.hook_facts(SEAT))[0], "asking")
        with patch.object(notify, "owner_said", return_value=[done + 60]):
            self.assertTrue(self.hook(CALL)["reason"].startswith("ak asks the owner this for you"))

    def test_only_a_seats_question_is_taken(self):
        self.assertIsNone(self.hook(dict(CALL, tool_name="Bash")))
        with patch.dict(os.environ, {"AK_RUN_ROLE": "worker"}):
            self.assertIsNone(self.hook(CALL))
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}):
            self.assertIsNone(self.hook(CALL))
        self.assertIsNone(self.kept())


if __name__ == "__main__":
    unittest.main()
