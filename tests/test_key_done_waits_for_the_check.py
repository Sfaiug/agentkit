"""A seat whose plan has every line done owes a done check of its work against what its owner
said, `ak orch check`'s, which `ak plan` makes: until one finds no gap the seat does not read
done and its stop goes back, and one that does counts until the owner says more.

The owner asks for a retry button and a receipt email; the plan holds the button alone.  The
first check names the email, quoting the owner; once the owner drops it, the next finds no gap.
`[done_check] on = false` leaves done as it was.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, on a Claude seat of tests/fixtures/akseat.py whose
transcript the test writes, with a fake harness of fakeadapter.py for the model, and the hooks
beside that program fired as tests/test_key_live_work_plan_line.py fires them.
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
from fixtures.hookdrive import ROOT

CONVERSATION = "7e1c9a42-5d3b-4f80-a6e2-1b9d4c7f0a53"
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
DROP = "Forget the receipt email; the retry button is enough."
PLANNED = "The upload page has a retry button"
DONE = "acme  done"
GAP = {"sh": f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- {shlex.quote(SECOND)} . | "
             f"head -n 1):1\" 'no receipt email' 'the owner asked for it' "
             f"--quote {shlex.quote(SECOND)}",
       "final": "Checked.", "hand_in": [["done"]]}
NONE = {"final": "Checked.", "hand_in": [["done"]]}


class DoneWaitsForTheCheck(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        seat = Seat(home, "acme", alive=False, record={"conversation": CONVERSATION})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.transcript = home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", "")
        self.converse(FIRST, SECOND)
        home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                   "written 2026-11-05 10:05 · done 0123456789ab\n")

    def configure(self, on=True):
        akconfig.write(self.home, ["opus"], extra='[done_check]\nmodel = "opus"'
                                                  + ("" if on else "\non = false"))

    def converse(self, *asked):
        """The seat's conversation: each of the owner's messages in `asked`, a minute apart,
        each answered."""
        turns = []
        for text in asked:
            turns += [{"type": "user", "message": {"role": "user", "content": text}},
                      {"type": "assistant", "message": {"role": "assistant", "content": [
                          {"type": "text", "text": "Done."}]}}]
        self.transcript.write_text("".join(
            json.dumps({**turn, "timestamp": f"2026-11-05T10:{n:02d}:00Z"}) + "\n"
            for n, turn in enumerate(turns)))

    def why(self):
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.splitlines()[0]

    def plan(self, step=None):
        """`ak plan` as the seat runs it, the model's turn doing `step` if it takes one."""
        if step:
            self.fake.behave(step)
        done = self.home.ak("plan", env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def hook(self, script, payload):
        done = self.home.run("bash", str(ROOT / "hooks" / script), input=json.dumps(payload),
                             env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def stop(self):
        """The reason a turn the owner's prompt began is sent back with at its end, or "" where
        its stop stands."""
        self.hook("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go",
                                    "session_id": CONVERSATION})
        out = self.hook("orchestrator-stop.sh", {"hook_event_name": "Stop",
                                                 "session_id": CONVERSATION,
                                                 "transcript_path": str(self.transcript)})
        return json.loads(out)["reason"] if out.strip() else ""

    def test_a_finished_plan_reads_done_once_a_check_finds_no_gap(self):
        self.configure()
        self.assertNotEqual(self.why(), DONE)
        self.assertNotEqual(self.stop(), "")
        out = self.plan(GAP)
        self.assertEqual(self.fake.n, 1)
        self.assertIn(SECOND, out)
        self.assertNotEqual(self.why(), DONE)
        self.converse(FIRST, SECOND, DROP)
        out = self.plan(NONE)
        self.assertEqual(self.fake.n, 2)
        self.assertNotIn(SECOND, out)
        self.assertEqual(self.why(), DONE)
        self.assertEqual(self.stop(), "")
        self.plan()
        self.assertEqual(self.fake.n, 2)

    def test_with_the_check_off_a_finished_plan_reads_done_and_ak_plan_takes_no_turn(self):
        self.configure(on=False)
        self.assertEqual(self.why(), DONE)
        self.plan()
        self.assertEqual(self.fake.n, 0)


if __name__ == "__main__":
    unittest.main()
