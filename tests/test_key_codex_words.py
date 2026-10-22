"""A Codex seat with no hook fact reads its word off its screen, by the rule `ak orch why` names.

Codex draws every dialog that waits on the owner, a turn under way, its prompt and a composer
holding a draft in its own way, and adapters/codex.toml's rules turn each into one of the words
the owner sees.  A dialog read as idle is a question nobody is told about; a turn read as idle
looks finished.  Each case is a capture of a real Codex screen shipped in tests/fixtures, shown
in turn in one seat's pane.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

# Each screen is tests/fixtures/codex-<name>-pane.txt, with the rule that reads it.
NEEDS_YOU = {"dialog": "asking.chooser", "hooks-review": "asking.chooser",
             "hooks-review-0160": "asking.chooser", "seat-server-turn": "asking.chooser",
             "question-up": "asking.question", "question-up-narrow": "asking.question"}
WORKING = {"working": "working.interrupt", "approved": "working.interrupt",
           "title-working": "working.interrupt", "title-working-accepted": "working.interrupt",
           "title-working-composed": "working.interrupt"}
AT_PROMPT = {"prompt": "prompt.composer", "auth": "prompt.composer",
             "auth-401": "prompt.composer", "resumed-warning": "prompt.suggestion",
             "sub-agent-done": "prompt.suggestion", "suggestion": "prompt.suggestion",
             "title-accepted": "prompt.suggestion", "title-idle": "prompt.suggestion"}
HOOKS_LISTING = ("remote-hooks", "remote-local-hooks", "seat-server-hooks")
DRAFTS = {"draft": "prompt.draft", "draft-two-lines": "prompt.draft",
          "draft-warning": "prompt.draft", "draft-wrapped": "prompt.draft",
          "title-composed": "prompt.draft", "model-picker": "draft.picker",
          "effort-picker": "draft.picker", "tall-line": "draft.rows",
          "tall-line-and-owner-words": "draft.rows"}
UNSENT = {"draft": "Fix the login redirect", "draft-two-lines": "line one of draft line two",
          "draft-warning": "a draft", "title-composed": "/rename lagoon",
          "draft-wrapped": "this is a draft I never sent and it is long enough to wrap across"
                           " the narrow composer line of the pane so that it takes two rows"}

FIELD = re.compile(r"^\s+(\w+):\s+(.*?)\s*$")
DECIDED = re.compile(r"^(\S+)\s+rule:\s+(\S+)$")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CodexWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # Codex's own login holds, so a login error drawn on the screen is all there is to read
        cls.home.write(".codex/auth.json", {"tokens": {"access_token": "acme-token"}})
        cls.seat = Seat(cls.home, "acme", model="astra", screen="codex-prompt-pane.txt")

    def why(self, name):
        """With that screen in the seat: (`ak orch why`'s first line, reason, evidence,
        authority, rule)."""
        self.seat.show(f"codex-{name}-pane.txt")
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.err)
        first, *rest = done.out.splitlines() or [""]
        fields = dict(found.groups() for found in map(FIELD.match, rest) if found)
        decided = DECIDED.match(fields.get("authority", ""))
        self.assertIsNotNone(decided, done.out)
        return (first, fields.get("reason"), fields.get("evidence"), *decided.groups())

    def assert_reads(self, cases, word, authority="screen", said=None):
        for name, rule in cases.items():
            with self.subTest(name):
                first, reason, evidence, *decided = self.why(name)
                self.assertEqual((first, *decided), (f"acme  {word}", authority, rule))
                if name in (said or {}):
                    self.assertEqual((reason, evidence), said[name])

    def test_a_dialog_or_question_waiting_on_the_owner_needs_you(self):
        self.assert_reads(NEEDS_YOU, "needs you")

    def test_a_turn_under_way_is_working(self):
        self.assert_reads(WORKING, "working")

    def test_a_turn_codex_retries_after_a_refusal_is_working(self):
        first, reason, *_rest = self.why("stall")
        self.assertEqual(first, "acme  working")
        self.assertRegex(reason or "", r"^retrying:.*\b429\b")

    def test_a_seat_at_its_prompt_is_idle_whatever_the_last_turn_said(self):
        # a login error at the prompt included: whether the login lapsed is asked of Codex
        self.assert_reads(AT_PROMPT, "idle")

    def test_the_hooks_listing_matches_no_rule_and_is_idle(self):
        self.assert_reads(dict.fromkeys(HOOKS_LISTING, "none"), "idle", authority="default")

    def test_text_in_the_composer_leaves_the_seat_idle(self):
        # the reason never carries the owner's text: the evidence is what the composer holds,
        # every row of it
        self.assert_reads(DRAFTS, "idle", said={name: ("-", words)
                                                for name, words in UNSENT.items()})


if __name__ == "__main__":
    unittest.main()
