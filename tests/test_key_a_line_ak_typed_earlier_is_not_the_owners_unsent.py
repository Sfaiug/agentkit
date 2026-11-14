"""A line ak typed into a seat earlier, back whole in its composer, is ak's to send, never the
owner's unsent text.

On 14 Nov 2026 a seat's row read `¶ unsent` over a line ak had typed there the day before: its
harness never took it, and after an idle compaction it was back whole in the composer, eleven
lines behind the last one ak typed there.  Only that last line read as ak's, so the owner was
asked to deal with ak's own line, and ak typed nothing more past what it read as their draft.
Here the seat's input record holds an older ak line and a newer one, the older whole in its
composer and nobody attached: its row marks nothing unsent, and one tick sends the line,
leaving the composer empty.  That line with a word more, or one typed into a conversation the
seat has left, is the owner's unsent text, and the tick sends none of it.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before a seat of
tests/fixtures/akseat.py at Claude Code's prompt, and this test fails against `/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

OLDER = "run 20261113-0915-fix-api is live: https://github.com/acme/api/pull/42."
NEWER = "run 20261114-0840-fix-docs ended PASS, merged; your wait is over."
CONVERSATION = "conv-acme"      # the one akseat's record names


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ALineAkTypedEarlier(unittest.TestCase):
    def seated(self, composer, into=CONVERSATION):
        """A Home whose seat `acme`, nobody attached, ak typed OLDER into, in conversation
        `into`, and NEWER after it, in its own: its composer holding `composer`."""
        home = Home()
        self.addCleanup(home.close)
        seat = Seat(home, "acme", model="opus")
        typed = time.time() - 86400
        home.write(".agentkit/state/input-acme.jsonl", "".join(
            json.dumps({"at": typed + after, "text": text, "source": "ak", "harness": "claude",
                        "conversation": conversation, "after": after}) + "\n"
            for after, (text, conversation) in enumerate(((OLDER, into), (NEWER, CONVERSATION)))))
        self.assertEqual(home.tmux("send-keys", "-t", seat.pane, "-l", composer).code, 0)
        deadline = time.monotonic() + 30
        while seat.typed() != composer:
            self.assertLess(time.monotonic(), deadline, seat.typed())
            time.sleep(0.05)
        seat.show("claude-prompt-pane.txt")     # drawn behind every key typed
        return home, seat

    def unsent(self, home):
        """What the seat's row marks unsent, off a draft it reads in the composer."""
        done = home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)
        data = json.loads((home.path / ".agentkit/state/seat-acme.json").read_text())
        self.assertEqual(data.get("state"), "draft")
        return data.get("unsent") or ""

    def tick(self, home):
        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_an_older_line_of_aks_is_marked_nowhere_and_sent(self):
        home, seat = self.seated(OLDER)
        self.assertEqual(self.unsent(home), "")
        self.tick(home)
        self.assertEqual(seat.wait_lines(1), [OLDER])
        self.assertNotIn(OLDER[:40], seat.capture())

    def test_that_line_and_a_word_more_is_the_owners(self):
        home, seat = self.seated(OLDER + " thanks")
        self.assertEqual(self.unsent(home), OLDER + " thanks")
        self.tick(home)
        self.assertEqual(seat.lines(), [])

    def test_that_line_typed_into_a_conversation_the_seat_left_is_the_owners(self):
        home, seat = self.seated(OLDER, into="conv-acme-before")
        self.assertEqual(self.unsent(home), OLDER)
        self.tick(home)
        self.assertEqual(seat.lines(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
