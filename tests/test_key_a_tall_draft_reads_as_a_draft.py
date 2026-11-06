"""A Claude Code draft taller than the rows its screen rules read is read as a draft.

On 5 Nov 2026 a seat holding the owner's long unsent message read as an empty prompt, and the
tick restarted it and lost the message: on Claude Code 2.1.318 a draft wrapped to seven rows,
or typed over six lines, had its prompt row above the eight rows the draft rule read.  Each
case is a capture of that real screen, in a seat nobody is in.  Black-box: the program `AK_BIN`
names reads it from outside (tests/fixtures/akseat.py), and this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

ASKED = "and then also check how the columns on the monitor page line up with the helper"
# each capture, and its text as the seat's row says it is unsent: whole, or its first 160
DRAFTS = {"claude-tall-draft-rows-pane.txt": f"{ASKED} {ASKED}"[:160].rstrip(),
          "claude-tall-draft-lines-pane.txt": " ".join(
              [f"point {n} of what I want next" for n in range(1, 6)] + ["last point"])}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TallDraft(unittest.TestCase):
    def test_a_draft_taller_than_the_rules_rows_is_the_owners_unsent_text(self):
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
