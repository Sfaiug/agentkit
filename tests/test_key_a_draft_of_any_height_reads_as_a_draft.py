"""A Claude Code draft of any height is read as a draft.

On 5 Nov 2026 a seat holding the owner's long unsent message still read as an empty prompt where
the draft was taller than eight rows: ten rows of it on Claude Code 2.1.318, more than the
seventeen it shows, scrolled inside its box with its prompt row above the rows the rules read,
and a line 2.1.291 scrolled at ten rows, one ending in the owner's own words.  Each case is a
capture of that real screen, in a seat nobody is in.  Black-box: the program `AK_BIN` names
reads it from outside (tests/fixtures/akseat.py), and this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

ASKED = " ".join(["and then also check how the columns on the monitor page line up with the helper"] * 3)
FAILED = "FAIL: a case. run 20261006-1534 finished " * 5
# each capture, and the start of the text its box shows as the seat's row says it is unsent:
# its first 160 characters, from the box's top row, the draft's own start scrolled away or not
DRAFTS = {"claude-ten-row-draft-pane.txt": ASKED[:160].rstrip(),
          "claude-scrolled-draft-pane.txt": ASKED[ASKED.index("with"):][:160].rstrip(),
          "claude-scrolled-line-pane.txt": FAILED[:160],
          "claude-scrolled-line-and-owner-words-pane.txt": FAILED[:160]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class DraftOfAnyHeight(unittest.TestCase):
    def test_a_draft_however_tall_is_the_owners_unsent_text(self):
        for screen, text in DRAFTS.items():
            with self.subTest(screen), Home() as home:
                Seat(home, "acme", model="opus", screen=screen)
                done = home.ak("orch", "why", "acme")
                self.assertEqual(done.code, 0, done.err)
                data = json.loads((home.path / ".agentkit/state/seat-acme.json").read_text())
                self.assertEqual((data.get("state"), data.get("rule"), data.get("unsent")),
                                 ("draft", "prompt.draft", text))


if __name__ == "__main__":
    unittest.main()
