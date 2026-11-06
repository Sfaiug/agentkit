"""`ak orch check SEAT` gives its model each answer the owner gave on the seat's question card,
beside the question and the choices the seat offered; a gap may quote the answer, never the
question.

The seat asks on an AskUserQuestion card which layout to use; the owner picks one and adds a
note asking for one more thing.  The model's turn hands in its gaps only where its workspace
holds the question, both choices and the answer: one quoting the note, one quoting the question.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
Claude seat of tests/fixtures/akseat.py whose transcript the test writes as Claude Code 2.1.318
records a card's answer, with a fake harness of fakeadapter.py for the model.
"""

import json
import re
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

CONVERSATION = "5b8d1e3a-2c7f-4a96-8e0b-3f1d6c9a7e25"
QUESTION = "Which layout should the settings page use?"
CHOICES = {"Compact": "Every setting on one short page.",
           "Tabbed": "One tab for each group of settings."}
NOTE = "Also add a search box above the tabs."


class OwnerAnswersKept(unittest.TestCase):
    def test_the_model_reads_the_answer_and_only_the_answer_makes_a_gap(self):
        with Home() as home:
            fake = fakeadapter.install(home, claude="pass")["claude"]
            seat = Seat(home, "acme", alive=False, record={"conversation": CONVERSATION})
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            questions = [{"question": QUESTION, "header": "Layout", "multiSelect": False,
                          "options": [{"label": label, "description": description}
                                      for label, description in CHOICES.items()]}]
            entries = [{"type": "assistant", "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "id": "toolu_acme", "name": "AskUserQuestion",
                            "input": {"questions": questions}}]}},
                       {"type": "user", "message": {"role": "user", "content": [
                           {"type": "tool_result", "tool_use_id": "toolu_acme",
                            "content": f'Your questions have been answered: "{QUESTION}"="Tabbed"'
                                       f" notes: {NOTE}. You can now continue with these "
                                       "answers in mind."}]},
                        "toolUseResult": {"questions": questions, "answers": {QUESTION: "Tabbed"},
                                          "annotations": {QUESTION: {"notes": NOTE}}}}]
            home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", "".join(
                json.dumps({**entry, "timestamp": f"2026-11-05T10:0{n}:00Z"}) + "\n"
                for n, entry in enumerate(entries)))
            akconfig.write(home, ["opus"], extra='[done_check]\nmodel = "opus"')
            # no gap at all unless the workspace holds the question, both choices and the answer
            sh = [f"grep -rqF -- {shlex.quote(given)} . || exit 1"
                  for given in (QUESTION, *CHOICES, *CHOICES.values(), NOTE)]
            sh += [f"{shlex.quote(AK)} hand-in finding "
                   f"\"$(grep -rlF -- {shlex.quote(quote)} . | head -n 1):1\" "
                   f"'not in the work' 'the owner asked for it' --quote {shlex.quote(quote)}"
                   for quote in (NOTE, QUESTION)]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(NOTE, done.out)
            self.assertNotIn(QUESTION, done.out + done.err)
            self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
