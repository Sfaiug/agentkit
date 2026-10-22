"""A seat's prompt is written down at once: what the seat is doing, and the turn it starts.

A seat's row reads its word from the fact its hooks keep (`hook-<seat>.json`), and the stop hook
judges a turn's end against the moment that turn's prompt arrived (`stop-<seat>.json`), with the
blocks it may make starting again from none.  A renamed seat's harness keeps its launch name for
its whole life, so its fact must land under the name the row reads now and its latch stay under
the launch name the stop hook reads it by.  Black-box: Claude's hooks as ak's adapter registers
them, fired as Claude fires them (tests/fixtures/hookdrive.py); this test fails against
`/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks

PROMPT = {"hook_event_name": "UserPromptSubmit", "prompt": "go", "session_id": "x"}


class PromptHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def state(self, name):
        path = self.home.path / ".agentkit" / "state" / name
        return json.loads(path.read_text()) if path.exists() else None

    def prompt(self, seat):
        """The prompt fired, and the moments just before and after it."""
        before = time.time()
        fired = self.hooks.fire("UserPromptSubmit", PROMPT, seat=seat)
        return before, fired, time.time()

    def test_a_prompt_writes_the_seat_working_and_starts_a_fresh_turn(self):
        self.home.write(".agentkit/state/session-acme.json",
                        {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"]})
        # the turn before ended sent back twice and asked back once
        self.home.write(".agentkit/state/stop-acme.json",
                        {"session": "acme", "turn": 1.0, "blocks": 2, "asked_back": True})
        before, fired, after = self.prompt("acme")
        self.assertEqual(fired, (0, "", "", []))
        fact = self.state("hook-acme.json")
        at = fact.get("at")
        self.assertEqual(fact, {"session": "acme", "event": "UserPromptSubmit", "kind": "",
                                "text": "", "at": at})
        self.assertTrue(before <= at <= after, (before, at, after))
        self.assertEqual(self.state("stop-acme.json"),
                         {"session": "acme", "turn": at, "blocks": 0})

    def test_a_renamed_seat_writes_its_fact_under_its_name_now_and_its_latch_under_its_first(self):
        self.home.write(".agentkit/state/session-fix-api.json", {"renamed": "parser"})
        self.home.write(".agentkit/state/session-parser.json", {"orchestrator": "opus"})
        _, fired, _ = self.prompt("fix-api")
        self.assertEqual(fired.code, 0, fired.err)
        fact = self.state("hook-parser.json")
        self.assertEqual((fact["event"], fact["session"]), ("UserPromptSubmit", "fix-api"))
        self.assertEqual(self.state("stop-fix-api.json")["turn"], fact["at"])
        self.assertIsNone(self.state("hook-fix-api.json"))
        self.assertIsNone(self.state("stop-parser.json"))

    def test_a_seat_renamed_twice_writes_its_fact_under_the_last_name(self):
        self.home.write(".agentkit/state/session-beta.json", {"renamed": "gamma"})
        self.home.write(".agentkit/state/session-gamma.json", {"renamed": "delta"})
        self.home.write(".agentkit/state/session-delta.json", {"orchestrator": "opus"})
        self.prompt("beta")
        self.assertEqual(self.state("hook-delta.json")["session"], "beta")
        self.assertIsNotNone(self.state("stop-beta.json"))
        self.assertIsNone(self.state("hook-gamma.json"))


if __name__ == "__main__":
    unittest.main()
