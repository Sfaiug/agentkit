"""Asking whether a seat is done reads its conversation only when its file changed.

A seat whose plan has every line done owes a done check until one that found no gap read what
its owner said; ak asks so for every seat row it draws, and every ask once read the seat's whole
conversation.  Now what it answered is kept with what it read, so an ask whose files are as they
were reads none of them, and one whose file changed reads it again.

A Claude seat's plan lines are all done, its owner asked for what the plan holds, and a done
check that found no gap read it: `ak orch why` reads the seat done.  With its transcript made
unreadable, its modification time put back, it still reads done, since nothing was read; once the
transcript is readable again and holds a new message of the owner's, it no longer reads done.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
Claude seat of tests/fixtures/akseat.py whose transcript the test writes, with a fake harness of
fakeadapter.py making the check.
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akseat import Seat

CONVERSATION = "6e1b9d42-7c3f-4a8e-b2d5-0f9a3c7e1d58"
ASKED = "Add a retry button to the upload page."
LATER = "Also email me a receipt after every upload."


def said(text, minute):
    return json.dumps({"type": "user", "timestamp": f"2026-11-05T10:0{minute}:00Z",
                       "message": {"role": "user", "content": text}}) + "\n"


class TranscriptReadOnce(unittest.TestCase):
    def test_an_unchanged_transcript_is_not_read_again_and_a_changed_one_is(self):
        with Home() as home:
            fake = fakeadapter.install(home, claude="pass")["claude"]
            seat = Seat(home, "acme", alive=False, record={"conversation": CONVERSATION})
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            transcript = home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl",
                                    said(ASKED, 0))
            home.write(".agentkit/state/plan-acme.md", "- [x] The upload page has a retry button\n")
            akconfig.write(home, ["opus"], extra='[done_check]\nmodel = "opus"')
            fake.behave({"final": "Checked.", "hand_in": [["done"]]})
            checked = home.ak("orch", "check", "acme")
            self.assertEqual(checked.code, 0, checked.out + checked.err)

            def word():
                why = home.ak("orch", "why", "acme")
                self.assertEqual(why.code, 0, why.out + why.err)
                return why.out.splitlines()[0].split()[1]

            self.assertEqual(word(), "done")
            was = transcript.stat()
            transcript.chmod(0)
            os.utime(transcript, ns=(was.st_atime_ns, was.st_mtime_ns))
            with self.assertRaises(PermissionError):
                transcript.open("rb")
            self.assertEqual(word(), "done")

            transcript.chmod(0o644)
            with transcript.open("a") as fh:
                fh.write(said(LATER, 1))
            self.assertNotEqual(word(), "done")


if __name__ == "__main__":
    unittest.main()
