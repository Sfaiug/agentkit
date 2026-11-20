"""A seat's failed turn keeps, in the fact its hook writes, the words the turn failed on.

Claude Code tells the hook of a turn ended on an API error what it failed on (2.1.328): its
`StopFailure` carries the `error` and the turn's `last_assistant_message`, a spent limit's own
words, which the conversation's transcript holds only later.  The fact ak keeps for the seat
(`hook-<seat>.json`) keeps them as its `text`, after a notice's own words.  A sub-agent's failure
is not the seat's turn's, and a seat run as a named agent sends an `agent_type` alone, which
nothing tells from a sub-agent's: either keeps no words, its event heard as ever.  Black-box:
Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py), in seats of tests/fixtures/akseat.py; this test fails against
`/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

LIMIT = "You've hit your weekly limit · resets Nov 21, 1am (Europe/Berlin)"
FAILED = {"error": "rate_limit", "last_assistant_message": LIMIT}
ASKS = "Claude needs your permission to use Bash"
# Each seat: the event its turn heard after its prompt, and the words its fact keeps.
SEATS = {
    "acme": ("StopFailure", FAILED, LIMIT),
    "beta": ("StopFailure", {**FAILED, "agent_id": "a1", "agent_type": "Explore"}, ""),
    "gamma": ("StopFailure", {**FAILED, "agent_type": "fix-api"}, ""),
    "delta": ("Notification", {"notification_type": "permission_prompt", "message": ASKS}, ASKS),
}


class FailedTurnsWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        hooks = Hooks(home)
        cls.facts = {}
        for name, (event, payload, _) in SEATS.items():
            Seat(home, name, alive=False)
            for heard, said in (("UserPromptSubmit", {"prompt": "go"}), (event, payload)):
                fired = hooks.fire(heard, {**said, "session_id": f"conv-{name}"}, seat=name)
                assert fired.code == 0, f"{name} {heard}: {fired.err}"
            path = home.path / ".agentkit" / "state" / f"hook-{name}.json"
            cls.facts[name] = json.loads(path.read_text())

    def test_each_seats_fact_is_its_last_event_with_the_words_it_keeps(self):
        for name, (event, _, text) in SEATS.items():
            with self.subTest(name):
                fact = self.facts[name]
                self.assertEqual((fact["session"], fact["event"], fact["text"]),
                                 (name, event, text))


if __name__ == "__main__":
    unittest.main()
