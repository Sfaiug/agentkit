"""A seat's prompt carries what changed in its rulebook, and handing it over records it as held.

A harness reads its rulebook only when it opens, so a seat left open across a change would keep
working to rules nobody holds any more.  ak tells the seat's own conversation instead, inside
the prompt that starts its next turn: what changed since the rulebook it holds, as a unified
diff, or the whole rulebook where ak has no record of that one.  It names no file to read and no
command to run, and the prompt after it carries nothing until the rules change again.  Where ak
cannot record the hand-over it hands nothing over, and the next prompt carries the change.  A
compaction leaves the conversation only its launch's rulebook, so its next prompt carries what
changed since that one.  The shipped rules alone are too long for Claude's prompt, so a whole
rulebook goes to a file the prompt names (tests/test_key_rulebook_news_too_long.py).  Black-box: Claude's hooks as ak's adapter registers them, fired as
Claude fires them (tests/fixtures/hookdrive.py); this test fails against `/bin/false`.
"""

import hashlib
import os
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home
from fixtures.hookdrive import Hooks

CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
SHIPPED = Path(AK).resolve().parents[1] / "orchestrator.md"   # ak's own rules, beside it
SILENT = (0, "", "", [])


def rulebook(own):
    """What a seat filed under no project holds: ak's rules, then the host's own."""
    return f"{SHIPPED.read_text().rstrip()}\n\n{own}"


class RulebookNews(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.hooks = Hooks(self.home)
        self.rules("Rule one.\n")

    def rules(self, own):
        self.home.write(".agentkit/rules.md", own)

    def launched(self):
        """A seat launched on the rules as they are now."""
        launched = rulebook("Rule one.\n")
        self.home.write(".agentkit/state/rulebook-acme.md", launched)
        self.seat(rulebook_sha=hashlib.sha256(launched.encode()).hexdigest())

    def seat(self, **record):
        """A Claude seat on its own conversation, launcher-issued."""
        self.home.write(".agentkit/state/session-acme.json",
                        {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"],
                         "cwd": str(self.home.path), "conversation": CONVERSATION,
                         "id_source": "launcher", "resumable": True, **record})

    def prompt(self):
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": CONVERSATION},
                                seat="acme")
        self.assertEqual(fired.code, 0, fired.err)
        return fired

    def told(self):
        """What the next prompt carries as Claude reads it, which sends it nowhere else."""
        fired = self.prompt()
        self.assertEqual(len(fired.said), 1, fired.out)
        output = fired.said[0]["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        news = output["additionalContext"]
        self.assertNotIn(str(self.home.path), news)
        self.assertNotIn("ak orch rules", news)
        return news

    def test_a_changed_rulebook_s_diff_arrives_in_the_next_prompt_and_only_there(self):
        self.launched()
        self.rules("Rule two.\n")
        news = self.told()
        self.assertIn("\n-Rule one.\n+Rule two.\n", news)
        self.assertLess(len(news), len(SHIPPED.read_text()) // 4)
        self.assertEqual(self.prompt(), SILENT)

    def test_with_no_record_of_the_rulebook_held_the_whole_one_is_pointed_to(self):
        gone = hashlib.sha256(b"a launch's rules ak no longer has\n").hexdigest()
        for record in ({}, {"rulebook_sha": gone}):
            with self.subTest(record=record):
                self.seat(**record)
                news = self.prompt().said[0]["hookSpecificOutput"]["additionalContext"]
                written = (self.home.path / ".agentkit/state/change-acme.md").read_text()
                self.assertIn(str(self.home.path / ".agentkit/state/change-acme.md"), news)
                self.assertIn(rulebook("Rule one.\n"), written)
                code = re.search(r"ak orch rules (\S+)\n*$", written)[1]
                done = self.home.ak("orch", "rules", code, env={"AGENTKIT_SESSION": "acme"})
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(self.prompt(), SILENT)

    @unittest.skipIf(os.geteuid() == 0, "root writes whatever a directory's mode")
    def test_a_hand_over_that_cannot_be_recorded_hands_nothing_and_the_next_prompt_does(self):
        self.launched()
        self.rules("Rule two.\n")
        state = self.home.path / ".agentkit" / "state"
        mode = state.stat().st_mode
        state.chmod(0o555)                  # nothing in ak's state can be written for now
        try:
            self.assertEqual(self.prompt(), SILENT)
        finally:
            state.chmod(mode)
        self.assertIn("\n-Rule one.\n+Rule two.\n", self.told())

    def test_after_a_compaction_the_next_prompt_carries_what_changed_since_the_launch(self):
        self.launched()
        self.assertEqual(self.prompt(), SILENT)
        self.rules("Rule two.\n")
        self.told()
        self.rules("Rule three.\n")
        self.assertIn("\n-Rule two.\n+Rule three.\n", self.told())
        compacted = self.hooks.fire("SessionStart",
                                    {"source": "compact", "session_id": CONVERSATION}, seat="acme")
        self.assertEqual(compacted, SILENT)
        self.assertIn("\n-Rule one.\n+Rule three.\n", self.told())
        self.assertEqual(self.prompt(), SILENT)


if __name__ == "__main__":
    unittest.main()
