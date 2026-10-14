"""A seat started again forgets what the harness before it was doing.

The hook facts are the last harness's: a seat that went mid-turn, or with a question up, read
`working` or `needs you` until its new harness's first Stop.  `orch.launch` drops them before the
new harness starts, and puts them back where it never did.  Offline: fake HOME, no tmux.
"""

import json
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch

SEAT = "acme-api"
FACT = {"session": SEAT, "event": "UserPromptSubmit", "kind": "", "text": "", "at": 9000.0}


class RelaunchForgetsHookFacts(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        config.hook_facts_path(SEAT).write_text(json.dumps(FACT))

    def test_a_started_seat_has_no_fact_from_the_harness_before(self):
        seen = []
        with patch.object(orch, "start", side_effect=lambda *_a, **_k:
                          seen.append(config.hook_facts_path(SEAT).exists())):
            orch.launch(SEAT, "opus", self.root, ["fake-harness"], "acme-conversation")
        self.assertEqual(seen, [False])          # gone before the new harness could write one
        self.assertFalse(config.hook_facts_path(SEAT).exists())

    def test_a_fact_the_new_harness_wrote_stays(self):
        def start(*_args, **_kw):
            config.hook_facts_path(SEAT).write_text(json.dumps(dict(FACT, at=9100.0)))

        with patch.object(orch, "start", side_effect=start):
            orch.launch(SEAT, "opus", self.root, ["fake-harness"], "acme-conversation")
        self.assertEqual(json.loads(config.hook_facts_path(SEAT).read_text())["at"], 9100.0)

    def test_a_start_that_failed_keeps_the_running_harnesss_fact(self):
        with patch.object(orch, "start", side_effect=config.Error("no tmux")):
            with self.assertRaises(config.Error):
                orch.launch(SEAT, "opus", self.root, ["fake-harness"], "acme-conversation")
        self.assertEqual(json.loads(config.hook_facts_path(SEAT).read_text()), FACT)


if __name__ == "__main__":
    unittest.main()
