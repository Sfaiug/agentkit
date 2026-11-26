"""A seat saved with no reviewer is told its changes land on their checks.

Each run a seat whose record marks no reviewer (`reviewers: []`) launches reviews nothing
(`record.review_off`), so its rulebook reads as review off does: its project's numbers with
review_rounds 0.  A seat with a reviewer reads its project's, and so does a record with no
`reviewers` key, whose builders review; a seat with no builder and no reviewer is told both.
Black-box: Claude's prompt hook as ak's adapter registers it, fired for a seat that holds no
rulebook yet, so it is told its rulebook whole (tests/fixtures/hookdrive.py); this test fails
against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks

CONVERSATION = "4b2e9f1c-7a3d-4c5e-9f0a-1b2c3d4e5f6a"
NO_REVIEW = "No review: a change lands on its checks; no reviewer."
THREE = "Three review rounds a change"
EXECUTORS_OFF = "Executors are off; the orchestrator builds every change itself."
READ = "\n\nOnce you have read all of the above"


class NoReviewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)
        cls.rig = Rig(cls.home, "widgets", files={
            "AGENTS.md": "---\ntests: none\nhealth: none\nusers: none\nreview_rounds: 3\n"
                         "---\nA project.\n"})
        cls.rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    def rulebook(self, name, **marks):
        """The whole rulebook the seat's first prompt hands it, without the line acknowledging it."""
        self.home.write(f".agentkit/state/session-{name}.json",
                        {"orchestrator": "opus", "workers": ["opus"], **marks,
                         "cwd": str(self.rig.path), "repo": str(self.rig.path),
                         "conversation": CONVERSATION, "id_source": "launcher", "resumable": True})
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": CONVERSATION},
                                seat=name)
        self.assertEqual((fired.code, len(fired.said)), (0, 1), fired.out + fired.err)
        change = self.home.path / f".agentkit/state/change-{name}.md"
        told = (change.read_text() if change.is_file() else
                fired.said[0]["hookSpecificOutput"]["additionalContext"])
        return told.split(READ)[0]

    def test_a_seat_with_no_reviewer_is_told_its_changes_land_on_their_checks(self):
        alone = self.rulebook("alone", reviewers=[])
        self.assertIn(NO_REVIEW, alone)
        self.assertNotIn(THREE, alone)

    def test_a_seat_with_a_reviewer_or_none_saved_reads_its_project_s(self):
        paired = self.rulebook("paired", reviewers=["opus"])
        self.assertIn(THREE, paired)
        self.assertNotIn(NO_REVIEW, paired)
        self.assertEqual(self.rulebook("unsaid"), paired)

    def test_a_seat_with_no_builder_and_no_reviewer_is_told_both(self):
        solo = self.rulebook("solo", workers=[], reviewers=[])
        self.assertIn(NO_REVIEW, solo)
        self.assertIn(EXECUTORS_OFF, solo)


if __name__ == "__main__":
    unittest.main()
