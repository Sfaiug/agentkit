"""A seat whose harness has not named its current conversation yet, as a fresh OpenCode seat's
launch names its session only at the first prompt, is checked on the conversations it left:
`ak orch check` reads the owner's words there.

A seat moved from Claude onto OpenCode left a conversation where the owner asks for a retry
button and then a receipt email; its plan holds the button alone, every line done, and its
OpenCode launch has reported no session.  `ak orch check` names the email, quoting the owner.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
seat of tests/fixtures/akseat.py whose record and left transcript the test writes, with a fake
harness of fakeadapter.py for the model.
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

LEFT = "5b8e2d14-7c3a-4f69-9e1d-2a6c8f0b4d37"
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
PLANNED = "The upload page has a retry button"
GAP = {"sh": f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- {shlex.quote(SECOND)} . | "
             f"head -n 1):1\" 'no receipt email' 'the owner asked for it' "
             f"--quote {shlex.quote(SECOND)}",
       "final": "Checked.", "hand_in": [["done"]]}


class UnnamedConversationChecked(unittest.TestCase):
    def test_the_check_finds_the_gap_in_the_conversation_it_left(self):
        with Home() as home:
            fake = fakeadapter.install(home, opencode="pass", claude="pass")["claude"]
            akconfig.write(home, ["mimo", "opus"], extra='[done_check]\nmodel = "opus"')
            seat = Seat(home, "acme", model="mimo", alive=False, record={
                "conversation": None, "opencode_launch": "a" * 32,
                "left": [{"harness": "claude", "conversation": LEFT}]})
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/{LEFT}.jsonl", "".join(
                json.dumps({"type": "user", "timestamp": f"2026-11-05T10:0{n}:00Z",
                            "message": {"role": "user", "content": text}}) + "\n"
                for n, text in enumerate((FIRST, SECOND))))
            home.write(".agentkit/state/plan-acme.md",
                       f"- [x] {PLANNED} · check: `true` · acme · written 2026-11-05 10:05 · "
                       "done 0123456789ab\n")
            fake.behave(GAP)
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(f'the owner: "{SECOND}"', done.out)


if __name__ == "__main__":
    unittest.main()
