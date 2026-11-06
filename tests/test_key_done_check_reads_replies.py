"""`ak orch check SEAT` gives its model the seat's whole conversation, the seat's replies
included, so a question the seat answered reads as answered; yet only the owner's words make a
gap, so a gap quoting the seat's reply is none.

The owner asks a question and asks for a retry button; the seat answers the question, and its
plan and runs hold no button.  The model's turn hands in its gaps only where its workspace holds
the seat's reply: one quoting the owner's ask for the button, one quoting the reply.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a Claude seat of
tests/fixtures/akseat.py whose transcript the test writes, with a fake harness of fakeadapter.py
for the model.
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

CONVERSATION = "9c2e4b17-6a3d-4f8e-b1c5-7d0a2e9f4b63"
QUESTION = "Why does the upload page time out on big files?"
REPLY = "Files over 100 MB outlast the proxy's 30 second limit, so the upload is cut off."
BUTTON = "Add a retry button to the upload page."


class DoneCheckReadsReplies(unittest.TestCase):
    def test_the_model_reads_the_seat_s_reply_and_only_the_owner_s_words_make_a_gap(self):
        with Home() as home:
            fake = fakeadapter.install(home, claude="pass")["claude"]
            seat = Seat(home, "acme", alive=False, record={"conversation": CONVERSATION})
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            entries = [{"type": "user", "message": {"role": "user", "content": QUESTION}},
                       {"type": "assistant", "message": {"role": "assistant",
                                                         "content": [{"type": "text",
                                                                      "text": REPLY}]}},
                       {"type": "user", "message": {"role": "user", "content": BUTTON}}]
            home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", "".join(
                json.dumps({**entry, "timestamp": f"2026-11-05T10:0{n}:00Z"}) + "\n"
                for n, entry in enumerate(entries)))
            akconfig.write(home, ["opus"], extra='[done_check]\nmodel = "opus"')
            # no gap at all unless the workspace holds the seat's reply
            sh = [f"grep -rqF -- {shlex.quote(REPLY)} . || exit 1"]
            sh += [f"{shlex.quote(AK)} hand-in finding "
                   f"\"$(grep -rlF -- {shlex.quote(quote)} . | head -n 1):1\" "
                   f"'not in the work' 'the owner asked for it' --quote {shlex.quote(quote)}"
                   for quote in (BUTTON, REPLY)]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(BUTTON, done.out)
            self.assertNotIn(REPLY, done.out + done.err)
            self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
