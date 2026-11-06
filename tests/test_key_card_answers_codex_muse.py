"""`ak orch check SEAT` gives its model each answer the owner gave on a Codex or a Muse seat's own
question card, beside the question and the choices the seat offered; a gap may quote the answer,
never the question, which Codex's reply repeats beside the owner's pick.

Each seat asks on its card which layout to use and the owner picks one; a second card it asked
holds no answer: Codex's left unanswered, Muse's put down with Esc.  The model's turn hands in its
gaps only where its workspace holds the answered question, both choices and the answer, and not
the other card's question: one quoting the answer, one quoting the question.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a seat of
tests/fixtures/akseat.py whose record the test writes as tests/test_codex_question_cards.py
(Codex 0.163) and tests/test_key_muse_native_question_after_new.py (Muse 1.4.12) hold a card,
with a fake harness of fakeadapter.py for the model.
"""

import json
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

QUESTION = "Which layout should the settings page use?"
CHOICES = ["Compact", "Tabbed"]
ANSWER = "Tabbed"
UNANSWERED = "Which colour should the settings page use?"
TOKEN = "a" * 32    # the seat's launch receipt


def codex(home):
    """A Codex seat whose rollout holds an async card the owner answered, and one they did not,
    beside the launch receipt that names it."""
    cwd = str(Seat(home, "acme", model="astra", alive=False,
                   record={"codex_launch": TOKEN}).cwd)
    reply = "<send_user_message_question_reply>\n" + json.dumps([{
        "answer": ANSWER, "question": QUESTION,
        "questionItemId": json.dumps(["request_user_input_async", "call-acme", 0])}]) + (
        "\n</send_user_message_question_reply>")

    def asked(call, question):
        return {"type": "response_item", "payload": {
            "type": "function_call", "name": "request_user_input_async", "call_id": call,
            "arguments": json.dumps({"questions": [{"title": question, "options": CHOICES}]})}}
    rows = [asked("call-acme", QUESTION),
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "UserMessage", "content": [{"type": "text", "text": reply}]}}},
            asked("call-left", UNANSWERED)]
    rollout = home.write("rollout.jsonl", "".join(json.dumps(row) + "\n" for row in [
        {"type": "session_meta", "payload": {"id": "thread-acme", "cwd": cwd}},
        *({**row, "timestamp": f"2026-11-05T10:0{n}:00Z"} for n, row in enumerate(rows))]))
    home.write(f".agentkit/state/codex-launch-{TOKEN}.json", {
        "launch": TOKEN, "cwd": cwd, "event": {
            "session_id": "thread-acme", "transcript_path": str(rollout),
            "hook_event_name": "SessionStart", "source": "startup", "cwd": cwd}})


def muse(home):
    """A Muse seat whose session log holds a card the owner answered, and one they put down."""
    Seat(home, "acme", model="spark", alive=False, record={"muse_launch": TOKEN})
    session = "5b8d1e3a-2c7f-4a96-8e0b-3f1d6c9a7e25"
    home.write(f".agentkit/state/muse-launch-{TOKEN}/session", session)

    def card(prompt, kind, **fields):
        return {"kind": f"user_input_prompt_{kind}", "prompt_id": prompt,
                "tool_call_id": f"{prompt}-call", **fields}

    def ask(question):
        return {"tool_name": "request_user_input", "questions": [
            {"id": "layout", "header": "Layout", "question": question,
             "options": [{"label": label} for label in CHOICES]}]}
    events = [card("acme-prompt", "requested", **ask(QUESTION)),
              card("acme-prompt", "settled", outcome="answered",
                   answers=[{"id": "layout", "selected_label": ANSWER}]),
              card("left-prompt", "requested", **ask(UNANSWERED)),
              card("left-prompt", "settled", outcome="interrupted")]
    home.write(f".local/share/muse/sessions/2026/11/05/{session}/session.jsonl", "".join(
        json.dumps({"schema_version": 1, "stream": {"kind": "session", "id": session},
                    "record_type": "event", "recorded_at": 1_762_336_800_000_000 + n * 60_000_000,
                    "payload": {"kind": "run", "run_id": "acme-run", "event": event}}) + "\n"
        for n, event in enumerate(events)))


class CardAnswersCodexMuse(unittest.TestCase):
    def check(self, harness, model, seat):
        with Home() as home:
            fake = fakeadapter.install(home, **{harness: "pass", "claude": "pass"})["claude"]
            seat(home)
            akconfig.write(home, [model, "opus"], extra='[done_check]\nmodel = "opus"')
            # no gap at all unless the workspace holds the question, both choices and the
            # answer, and nothing of the card that holds no answer
            sh = [f"grep -rqF -- {shlex.quote(given)} . || exit 1"
                  for given in (QUESTION, *CHOICES, ANSWER)]
            sh += [f"! grep -rqF -- {shlex.quote(UNANSWERED)} . || exit 1"]
            sh += [f"grep -rlF -- {shlex.quote(quote)} . | head -n 1 | while read -r file; do "
                   f"{shlex.quote(AK)} hand-in finding \"$file:1\" 'not in the work' "
                   f"'the owner asked for it' --quote {shlex.quote(quote)}; done"
                   for quote in (ANSWER, QUESTION)]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(f'the owner: "{ANSWER}"', done.out)
            self.assertNotIn(QUESTION, done.out + done.err)
            self.assertEqual(fake.n, 1)

    def test_a_codex_seat_s_card_answer_is_the_owner_s_and_its_question_is_not(self):
        self.check("codex", "astra", codex)

    def test_a_muse_seat_s_card_answer_is_the_owner_s_and_its_question_is_not(self):
        self.check("muse", "spark", muse)


if __name__ == "__main__":
    unittest.main()
