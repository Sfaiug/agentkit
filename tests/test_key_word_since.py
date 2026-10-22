"""A seat's word keeps the moment it began for as long as it holds, and a new word starts anew.

Every reader of a seat -- `ak orch why`, the tick, the menu -- decides its word again, and the
seat's record keeps `word_since`, when that word began: the why screen's `since:`, and what a
row's age counts from.  Read again with the word unchanged, it stays where it was, whoever
reads; read with another word, it starts at that read, never at the old word's start.  A since
that moved on every read would make a seat a day stuck look a second old.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before a seat of
tests/fixtures/akseat.py, judged by the record it writes under HOME and what it prints.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akseat import Seat

LONG_AGO = 1000    # 1970-01-01 00:16 UTC: no read could take it for its own moment


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WordSince(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])     # the audit off: a tick opens no seat of its own
        self.seat = Seat(self.home, "acme", screen="claude-prompt-pane.txt")
        self.home.write(".agentkit/state/seat-acme.json",
                        {"word": "idle", "word_since": LONG_AGO})

    def word(self):
        """(word, word_since) as the seat's record keeps them."""
        record = json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())
        return record.get("word"), record.get("word_since")

    def why(self):
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        return done.out

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_reads_that_find_the_same_word_keep_when_it_began(self):
        said = self.why()
        self.assertEqual(said.split()[:2], ["acme", "idle"])
        since, = [line.strip() for line in said.splitlines() if line.strip().startswith("since:")]
        self.assertIn("1970-01-01 00:16", since)
        self.assertEqual(self.word(), ("idle", LONG_AGO))
        done = self.home.tick()       # the tick is a reader too
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.word(), ("idle", LONG_AGO))

    def test_a_new_word_begins_at_the_read_that_found_it_and_then_keeps_that(self):
        self.seat.show("claude-working-pane.txt")
        before = time.time()
        self.assertEqual(self.why().split()[:2], ["acme", "working"])
        word, since = self.word()
        self.assertEqual(word, "working")
        self.assertGreaterEqual(since, int(before))     # a build may keep whole seconds
        self.why()
        self.assertEqual(self.word(), ("working", since))


if __name__ == "__main__":
    unittest.main()
