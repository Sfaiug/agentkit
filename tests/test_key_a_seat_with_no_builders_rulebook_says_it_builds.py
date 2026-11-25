"""A seat saved with no builder is told it builds every change itself, in PRs of its size.

`ak run <task>` refuses a seat whose record marks no builder (`workers: []`), so its rulebook
reads as executors off does: its project's numbers, else the host's, with executor_lines 0.  A
seat with a builder reads as before, and so does one with no builder where orchestrator_lines is
0, where nobody could build, and a seat launched before its record is saved, whatever a seat
before it under its name saved.  Black-box: Claude's prompt hook as ak's adapter registers it,
fired for a seat that holds no rulebook yet, so it is told its rulebook whole
(tests/fixtures/hookdrive.py), and a seat opened from a terminal on the echo harness
(tests/test_key_open_seat_rulebook.py); this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, shipped_rules
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks
from test_key_open_seat_rulebook import echo_home

CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
EXECUTORS_OFF = "Executors are off; the orchestrator builds every change itself."
BUILDS = "as a task and an executor builds it"
READ = "\n\nOnce you have read all of the above"


class NoBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def rulebook(self, name, workers, repo=None):
        """The whole rulebook the seat's first prompt hands it, without the line acknowledging it."""
        self.home.write(f".agentkit/state/session-{name}.json",
                        {"orchestrator": "opus", "workers": workers, "reviewers": ["opus"],
                         "cwd": str(repo or self.home.path), "conversation": CONVERSATION,
                         "id_source": "launcher", "resumable": True,
                         **({"repo": str(repo)} if repo else {})})
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": CONVERSATION},
                                seat=name)
        self.assertEqual((fired.code, len(fired.said)), (0, 1), fired.out + fired.err)
        change = self.home.path / f".agentkit/state/change-{name}.md"
        told = (change.read_text() if change.is_file() else
                fired.said[0]["hookSpecificOutput"]["additionalContext"])
        return told.split(READ)[0]

    def test_a_seat_with_no_builder_builds_every_change_in_prs_of_its_size(self):
        solo = self.rulebook("solo", [])
        self.assertIn("you build at most 50 added lines per PR; split larger changes", solo)
        self.assertIn(EXECUTORS_OFF, solo)
        self.assertNotIn(BUILDS, solo)
        self.assertIn(shipped_rules().rstrip(), self.rulebook("pair", ["opus"]))

    def test_with_no_orchestrator_lines_a_seat_with_no_builder_reads_as_one_with_a_builder(self):
        rig = Rig(self.home, "widgets", files={
            "AGENTS.md": "---\ntests: none\nhealth: none\nusers: none\norchestrator_lines: 0\n"
                         "---\nA project.\n"})
        rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        alone = self.rulebook("alone", [], rig.path)
        self.assertIn("you build at most 0 added lines; anything bigger you write " + BUILDS, alone)
        self.assertEqual(alone, self.rulebook("duo", ["opus"], rig.path))


    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_launch_reads_no_builders_off_the_seat_before_it_under_its_name(self):
        with echo_home() as home:
            state = home.path / ".agentkit/state"
            home.write(".agentkit/state/session-demo.json",
                       {"orchestrator": "two", "workers": [], "reviewers": ["two"],
                        "cwd": str(home.path)})
            opened = home.ak("orch", "demo", "--model", "two", "--workers", "one", tty=True,
                             cwd=home.path)
            self.assertEqual(opened.code, 0, opened.err)
            self.assertEqual(json.loads((state / "session-demo.json").read_text())["workers"],
                             ["one"])
            self.assertIn(shipped_rules().rstrip(), (state / "rulebook-demo.md").read_text())


if __name__ == "__main__":
    unittest.main()
