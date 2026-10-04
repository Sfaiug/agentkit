"""A turn the owner interrupted reads at its prompt, though its harness never reported it ending.

Claude Code 2.1.289 sends no Stop and no idle_prompt after an Esc: the seat's hook record keeps
its `UserPromptSubmit`, and without this the seat read `working` until the next prompt and
nothing could be handed back to it.  Its screen says so in one line right above the composer,
which the next prompt's echo pushes away.  hooks/seat-state.sh runs as the harness runs it; the
screens are real captures with invented names.
"""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, watch

NOW = 1_800_000_000
SEAT = "fix-api"
FIX = REPO / "tests/fixtures"
INTERRUPTED = (FIX / "claude-interrupted-pane.txt").read_text(encoding="utf-8")
NEXT_TURN = (FIX / "claude-after-interrupt-next-turn-pane.txt").read_text(encoding="utf-8")
RUNNING = (FIX / "claude-working-after-question-pane.txt").read_text(encoding="utf-8")


class InterruptedTurn(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})

    def prompt(self, text):
        """A prompt through hooks/seat-state.sh, as the harness submits one; the record after."""
        done = subprocess.run(
            ["bash", str(REPO / "hooks/seat-state.sh")], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": text}),
            env={"PATH": os.environ["PATH"], "HOME": str(self.root), "AGENTKIT_SESSION": SEAT,
                 "AK_RUN_ROLE": "orchestrator", "IDLE_COMPACT_STATE": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.root / f".agentkit/state/hook-{SEAT}.json").read_text())

    def looked(self, pane, fact):
        config.hook_facts_path(SEAT).write_text(json.dumps(fact))
        with patch.object(watch, "pane_text", return_value=pane) as read:
            free = watch.at_prompt({"name": SEAT}, cfg=self.cfg)
        self.assertTrue(read.called)
        live = watch.classify("claude", watch.pane_tail(pane), fact, None, {}, NOW)
        word = watch.session_state(SEAT, NOW, session={"name": SEAT, "attached": False},
                                   cfg=self.cfg, records=[], live=live, harness="claude",
                                   auth_out={}, gh_out={}, token_out={}, previous={})["word"]
        return word, free

    def test_an_interrupted_turn_is_at_its_prompt_and_free_to_type_into(self):
        fact = self.prompt("Run the acme tests.")
        self.assertEqual(self.looked(RUNNING, fact), ("working", False))
        self.assertEqual(self.looked(INTERRUPTED, fact), ("needs you", True))

    def test_the_next_prompt_after_an_interrupt_is_a_turn_running(self):
        """Its echo pushes the notice away from the composer: that turn is not the one that ended."""
        self.prompt("Run the acme tests.")
        fact = self.prompt("Run them in the foreground.")
        self.assertEqual(self.looked(NEXT_TURN, fact), ("working", False))
        self.assertIn("Interrupted · What should Claude do instead?", NEXT_TURN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
