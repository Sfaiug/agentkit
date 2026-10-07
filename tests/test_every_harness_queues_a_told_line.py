"""Every harness holds a line typed while its turn runs, so a told line reaches a working seat.

Each pane is a real capture, with its attributes, of a seat mid-turn holding one typed line
(`claude-queued-midturn-pane.txt` is Claude Code 2.1.289's; the others were taken on 7 Oct from
Codex 0.161.0, Grok Build 1.0.46, Muse 1.4.3, OpenCode 2.0.24 and Antigravity 1.3.1).  What the
tick asks before it types into a seat mid-turn is asked of each: the turn in flight, its harness
holding a typed line, no question up and its composer empty.
"""

import json
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch, watch

MODELS = {"claude": "opus", "codex": "astra", "grokbuild": "grok", "muse": "spark",
          "opencode": "mimo", "antigravity": "gemini"}


class EveryHarnessQueues(Sandbox):
    def test_a_working_seat_of_every_harness_takes_a_told_line(self):
        for harness, model in MODELS.items():
            with self.subTest(harness=harness):
                self.assertEqual(config.model(self.cfg, model)["harness"], harness)
                pane = (REPO / f"tests/fixtures/{harness}-queued-midturn-pane.txt").read_text(
                    encoding="utf-8")
                name = f"acme-{harness}"
                config.save_session(self.cfg, name, model, ["opus"], {"cwd": str(self.root)})
                # the turn began by the seat's own hook, where its harness has hooks
                config.hook_facts_path(name).write_text(json.dumps(
                    {"session": name, "event": "UserPromptSubmit", "kind": "", "text": "",
                     "at": time.time() - 60}))
                session = {"name": name, "created": 1, "legacy": False}
                with patch.object(orch, "sessions", return_value=[session]):
                    self.assertTrue(watch._turn_in_flight(
                        harness, watch.live_state(session, harness, pane=pane, cfg=self.cfg))[0])
                    self.assertTrue(watch.takes_line(session, cfg=self.cfg, pane=pane,
                                                     midturn=True))
                    self.assertFalse(watch.asking(name, harness, pane))
                    self.assertEqual(watch.composer_draft(harness, pane), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
