"""A Codex or Muse card record of any other shape than the one the harness writes (Codex 0.163's
in tests/test_codex_question_cards.py, Muse 1.4.12's in
tests/test_key_muse_native_question_after_new.py) answers nothing: the done check would take
its answer for the owner's words.
"""

import copy
import json
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import harness
from agentkit.harness import codex, muse

QUESTION, CHOICES, ANSWER = "Which layout?", ["Compact", "Tabbed"], "Tabbed"
READ = [{"question": QUESTION, "answer": ANSWER,
         "choices": [{"label": label, "description": ""} for label in CHOICES]}]


def codex_card(call):
    reply = "<send_user_message_question_reply>\n" + json.dumps([{
        "answer": ANSWER, "question": QUESTION,
        "questionItemId": json.dumps(["request_user_input_async", call, 0])}]) + (
        "\n</send_user_message_question_reply>")
    return [{"timestamp": "2026-11-05T10:00:00Z", "type": "response_item", "payload": {
                "type": "function_call", "name": "request_user_input_async", "call_id": call,
                "arguments": json.dumps({"questions": [{"title": QUESTION, "options": CHOICES}]})}},
            {"timestamp": "2026-11-05T10:01:00Z", "type": "event_msg", "payload": {
                "type": "item_completed", "item": {"type": "UserMessage", "content": [
                    {"type": "text", "text": reply}]}}}]


REQUEST = {"kind": "user_input_prompt_requested", "prompt_id": "acme-prompt",
           "tool_call_id": "acme-call", "tool_name": "request_user_input", "questions": [
               {"id": "layout", "header": "Layout", "question": QUESTION,
                "options": [{"label": label} for label in CHOICES]}]}


def muse_card(request, **settled):
    events = [request, {"kind": "user_input_prompt_settled", "prompt_id": "acme-prompt",
                        "tool_call_id": "acme-call", "outcome": "answered",
                        "answers": [{"id": "layout", "selected_label": ANSWER}], **settled}]
    return [{"schema_version": 1, "stream": {"kind": "session", "id": "acme-thread"},
             "record_type": "event", "recorded_at": 1_762_336_800_000_000 + n,
             "payload": {"kind": "run", "run_id": "acme-run", "event": event}}
            for n, event in enumerate(events)]


def changed(**change):
    """REQUEST with its question's `change`s, `option` its first option's."""
    request = copy.deepcopy(REQUEST)
    question = request["questions"][0]
    question["options"][0].update(change.pop("option", {}))
    question.update(change)
    return request


class CardAnswerShapes(Sandbox):
    def read(self, name, module, reader, rows):
        """`answers` of that harness, its record the JSON lines `rows`, without their times."""
        log = self.root / "record.jsonl"
        log.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with patch.object(module, reader, return_value=str(log)):
            return [{key: value for key, value in answer.items() if key != "at"}
                    for answer in harness.load(name).answers({}, None, "acme-thread")]

    def test_codex_reads_a_card_its_call_names(self):
        self.assertEqual(self.read("codex", codex, "transcript", codex_card("call-acme")), READ)
        for call in (None, 42, False):
            with self.subTest(call=call):
                self.assertEqual(self.read("codex", codex, "transcript", codex_card(call)), [])

    def test_muse_reads_a_request_user_input_card_in_words(self):
        self.assertEqual(self.read("muse", muse, "session_log", muse_card(REQUEST)), READ)
        for shape, rows in {
                "another tool": muse_card({**REQUEST, "tool_name": "another_tool"}),
                "an unnamed card": muse_card({**REQUEST, "prompt_id": None}, prompt_id=None),
                "a question not in words": muse_card(changed(question=None)),
                "a choice not in words": muse_card(changed(option={"label": 42})),
                "a description not in words": muse_card(changed(option={"description": []})),
                "nothing picked": muse_card(REQUEST, answers=[]),
                "a blank pick": muse_card(REQUEST, answers=[{"id": "layout",
                                                             "selected_label": " "}]),
                "an Esc": muse_card(REQUEST, outcome="interrupted")}.items():
            with self.subTest(shape):
                self.assertEqual(self.read("muse", muse, "session_log", rows), [])


if __name__ == "__main__":
    unittest.main()
