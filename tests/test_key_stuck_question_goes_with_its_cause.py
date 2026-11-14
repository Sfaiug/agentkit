"""AK_BIN's hooks retire only ak's stuck question when its cause ends, in an isolated HOME."""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks

OWN = "Which schema should acme use?"
SAID = "The parser still needs work."


class StuckQuestionGoesWithItsCause(unittest.TestCase):
    def test_only_the_stuck_question_goes_when_the_seat_has_an_ending_of_its_own(self):
        for ending in ("wait", "plan", "question", "stuck"):
            with self.subTest(ending=ending), Home() as home:
                hooks = Hooks(home)
                plan = home.write(".agentkit/state/plan-acme.md", "- [ ] fix the parser\n")

                def fire(event, **payload):
                    result = hooks.fire(event, payload, seat="acme", finished=True)
                    self.assertEqual(result.code, 0, result.err)
                    return result.said

                def read(kind):
                    return json.loads((home.path / f".agentkit/state/{kind}-acme.json").read_text())

                fire("UserPromptSubmit", prompt="go")
                for stop in range(3):
                    said = fire("Stop", last_assistant_message=SAID)
                    self.assertEqual([out["decision"] for out in said],
                                     ["block"] if stop < 2 else [])
                stuck = read("seat")["unasked"]["text"]
                self.assertIn("How should this seat go on?", stuck)
                done = home.ak("notify", "needs", stuck, "--session", "acme")
                self.assertEqual(done.code, 0, done.err)
                notice, card = read("notify"), read("card")
                self.assertEqual(notice["text"], stuck)
                fire("UserPromptSubmit", prompt="Run acme-parser finished.")
                if ending == "wait":
                    home.write(".agentkit/runs/acme-parser/run.json", {
                        "run_id": "acme-parser", "launched_session": "acme", "state": "running"})
                    done = home.ak("wait", "acme-parser", env={"AGENTKIT_SESSION": "acme"})
                    self.assertEqual(done.code, 0, done.err)
                elif ending == "plan":
                    plan.write_text("- [x] fix the parser\n")
                elif ending == "question":
                    done = home.ak("notify", "needs", OWN, "--session", "acme")
                    self.assertEqual(done.code, 0, done.err)
                self.assertEqual(fire("Stop", last_assistant_message=(
                    OWN if ending == "question" else SAID)), [])
                after = read("notify")
                if ending == "stuck":
                    self.assertEqual(after, notice)
                    self.assertEqual(read("card"), card)
                    self.assertEqual(read("seat")["unasked"]["text"], stuck)
                else:
                    self.assertIsNone(read("seat").get("unasked"))
                    if ending == "question":
                        self.assertEqual(after["text"], OWN)
                        self.assertFalse(after.get("seen"))
                    else:
                        self.assertTrue(after.get("seen"))
                        self.assertGreater(read("card")["answered_at"], card["since"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
