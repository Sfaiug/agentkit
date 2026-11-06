"""`ak orch check SEAT` gives its model each answer the owner gave on a Codex seat's Plan-mode
question card, `request_user_input`, beside the question and the choices with their descriptions;
a gap may quote the pick or the note added to it, never the question.  Codex keeps that answer as
the call's output, not as a message of the owner's.

The seat's rollout holds the card as a real Codex 0.167 rollout held it on 6 Nov 2026, answered
with a pick and a note, and a second card whose call has no output; the pick's label begins as
Codex begins a note, and stays whole.  The model's turn hands in its gaps only where its
workspace holds the answered question, both choices with their descriptions and the pick with
its note, and not the other card's question: one quoting the whole pick, one the note, one the
question.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a seat of tests/fixtures/akseat.py whose launch receipt names the
rollout, with a fake harness of fakeadapter.py for the model, as
tests/test_key_card_answers_codex_muse.py has it for an async card.
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

QUESTION = "Which colour should the acme banner be?"
CHOICES = {"Red": "Make the acme banner red.", "user_note: Blue": "Make the acme banner blue."}
PICK, NOTE = "user_note: Blue", "and make the text bold"
UNANSWERED = "Which size should the acme banner be?"
TOKEN = "a" * 32    # the seat's launch receipt


def card(call, key, question):
    return {"type": "function_call", "name": "request_user_input", "call_id": call,
            "arguments": json.dumps({"questions": [{
                "header": "Banner", "id": key, "question": question,
                "options": [{"label": label, "description": description}
                            for label, description in CHOICES.items()]}]})}


class CardAnswersCodexPlan(unittest.TestCase):
    def test_a_plan_mode_card_s_pick_and_note_are_the_owner_s_and_its_question_is_not(self):
        with Home() as home:
            fake = fakeadapter.install(home, codex="pass", claude="pass")["claude"]
            cwd = str(Seat(home, "acme", model="astra", alive=False,
                           record={"codex_launch": TOKEN}).cwd)
            items = [card("call_616e", "acme_banner_colour", QUESTION),
                     {"type": "function_call_output", "call_id": "call_616e",
                      "output": json.dumps({"answers": {"acme_banner_colour": {
                          "answers": [PICK, f"user_note: {NOTE}"]}}})},
                     card("call_left", "acme_banner_size", UNANSWERED)]
            rollout = home.write("rollout.jsonl", "".join(json.dumps(row) + "\n" for row in [
                {"type": "session_meta", "payload": {"id": "thread-acme", "cwd": cwd}},
                *({"timestamp": f"2026-11-06T10:0{n}:00Z", "type": "response_item",
                   "payload": item} for n, item in enumerate(items))]))
            home.write(f".agentkit/state/codex-launch-{TOKEN}.json", {
                "launch": TOKEN, "cwd": cwd, "event": {
                    "session_id": "thread-acme", "transcript_path": str(rollout),
                    "hook_event_name": "SessionStart", "source": "startup", "cwd": cwd}})
            akconfig.write(home, ["astra", "opus"], extra='[done_check]\nmodel = "opus"')
            # no gap at all unless the workspace holds the question, both choices with their
            # descriptions, the pick on a line of its own and the note, and nothing of the card
            # whose call has no output
            sh = [f"grep -rqF -- {shlex.quote(given)} . || exit 1"
                  for given in (QUESTION, *CHOICES, *CHOICES.values(), NOTE)]
            sh += [f"grep -rqxF -- {shlex.quote(PICK)} . || exit 1",
                   f"! grep -rqF -- {shlex.quote(UNANSWERED)} . || exit 1"]
            sh += [f"grep -rlF -- {shlex.quote(quote)} . | head -n 1 | while read -r file; do "
                   f"{shlex.quote(AK)} hand-in finding \"$file:1\" 'not in the work' "
                   f"'the owner asked for it' --quote {shlex.quote(quote)}; done"
                   for quote in (PICK, NOTE, QUESTION)]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(f'the owner: "{PICK}"', done.out)
            self.assertIn(f'the owner: "{NOTE}"', done.out)
            self.assertNotIn(QUESTION, done.out + done.err)
            self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
