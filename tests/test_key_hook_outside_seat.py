"""A seat's hooks write and say nothing where there is no seat's turn to keep.

A headless `ak worker` runs the same harness with the same hooks, a harness started by hand has
no seat, and a seat's name is one component of a path: none of them may move a seat's row or
write outside its own records.  A sub-agent's prompt and Stop pass through the seat's hooks too,
but its turn is not the seat's: written down, its prompt would start the seat's turn afresh and
its Stop end it.  A session starting is no fact of its own, and stdin no harness would send is
swallowed, since a hook that fails loudly is a harness that stops.  Black-box: Claude's hooks as
ak's adapter registers them, fired as Claude fires them (tests/fixtures/hookdrive.py); this test
fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

QUIET = (0, "", "", [])
PROMPT = {"hook_event_name": "UserPromptSubmit", "prompt": "go", "session_id": "x"}
RECORD = "session-acme.json"
# Each spelling a harness marks a sub-agent's own event with; any one alone marks it.
SUB_AGENT = ("agent_id", "agentId", "agent_type", "agentType", "subagentType", "subagent_type")


class HooksOutsideASeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)
        cls.state = cls.home.path / ".agentkit" / "state"
        Seat(cls.home, "acme", alive=False)

    def setUp(self):
        for path in self.state.iterdir():
            if path.name != RECORD:
                path.unlink()

    def written(self):
        return sorted(path.name for path in self.state.iterdir())

    def test_a_worker_no_seat_or_a_seat_name_that_is_a_path_writes_and_prints_nothing(self):
        for label, seat, env in (("worker", "acme", {"AK_RUN_ROLE": "worker"}),
                                 ("no seat", None, None), ("a/b", "a/b", None),
                                 ("..", "..", None), (".", ".", None)):
            for event, payload in (("UserPromptSubmit", PROMPT), ("Stop", {})):
                with self.subTest(label, event=event):
                    fired = self.hooks.fire(event, payload, seat=seat, env=env)
                    self.assertEqual(fired, QUIET)
                    self.assertEqual(self.written(), [RECORD])

    def test_a_sub_agents_prompt_and_stop_leave_the_seats_turn_alone(self):
        latch = {"session": "acme", "turn": 5, "blocks": 1}
        self.home.write(".agentkit/state/stop-acme.json", latch)
        for key in SUB_AGENT:
            with self.subTest(key):
                self.assertEqual(self.hooks.fire("UserPromptSubmit", {**PROMPT, key: "a1"}),
                                 QUIET)
                self.assertEqual(self.hooks.fire("Stop", {key: "explore"}), QUIET)
                self.assertEqual(json.loads((self.state / "stop-acme.json").read_text()), latch)
                self.assertEqual(self.written(), [RECORD, "stop-acme.json"])

    def test_a_session_starting_writes_no_fact_and_says_nothing(self):
        fired = self.hooks.fire("SessionStart", {"source": "startup", "session_id": "x"})
        self.assertEqual(fired, QUIET)
        self.assertEqual(self.written(), [RECORD])

    def test_stdin_that_is_not_json_is_swallowed_by_every_hook(self):
        for event in self.hooks.settings["hooks"]:
            for command in self.hooks.commands(event):
                with self.subTest(event, command=command):
                    done = self.home.run("sh", "-c", command, input="not json",
                                         env={"AGENTKIT_SESSION": "acme"})
                    self.assertEqual(done, (0, "", ""))
                    self.assertEqual(self.written(), [RECORD])


if __name__ == "__main__":
    unittest.main()
