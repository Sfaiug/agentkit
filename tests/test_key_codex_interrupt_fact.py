"""A Codex seat's Interrupt is written down every time, though it means what a Stop means.

The owner's Esc ends a Codex turn with an `Interrupt` event, which says the seat is at its
prompt, as a Stop does.  A notice that says only what the seat's fact (`hook-<seat>.json`)
already says is not written again, but an interrupt always is, with the moment it arrived: it is
the owner stopping the turn, so the seat rests whatever its plan still owes, and only the fact
can say a turn ended that way and when.  Black-box: Codex's launch registers
`bash <install>/hooks/seat-state.sh` for each event it emits, and this runs that command as Codex
does, the event's JSON on stdin in the seat's environment; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

SEAT_STATE = ROOT / "hooks" / "seat-state.sh"


class CodexInterrupt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def seat(self, name):
        self.home.write(f".agentkit/state/session-{name}.json",
                        {"orchestrator": "astra", "workers": ["astra"]})
        return name

    def fire(self, event, seat, **payload):
        """That event through the hook Codex runs for it; the seat's fact after it."""
        done = self.home.run("bash", str(SEAT_STATE),
                             input=json.dumps({"hook_event_name": event, **payload}),
                             env={"AGENTKIT_SESSION": seat})
        self.assertEqual(done.code, 0, done.err)
        path = self.home.path / ".agentkit" / "state" / f"hook-{seat}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_an_interrupt_is_written_after_a_stop_and_again_after_itself(self):
        name = self.seat("acme")
        stopped = self.fire("Stop", name)
        self.assertEqual(stopped["event"], "Stop")
        first = self.fire("Interrupt", name, turn_id="turn-1")
        self.assertEqual((first["session"], first["event"]), (name, "Interrupt"))
        self.assertGreater(first["at"], stopped["at"])
        second = self.fire("Interrupt", name, turn_id="turn-2")
        self.assertEqual(second["event"], "Interrupt")
        self.assertGreater(second["at"], first["at"])

    def test_a_notice_saying_what_the_fact_says_is_not_written_again(self):
        # beside the interrupt: a second permission request asks what the first one asked
        name = self.seat("beta")
        self.fire("UserPromptSubmit", name, prompt="Touch a file outside the workspace.")
        asked = self.fire("PermissionRequest", name, tool_name="Bash", tool_use_id="exec-1")
        self.assertEqual((asked["event"], asked["kind"]), ("PermissionRequest", "Bash"))
        again = self.fire("PermissionRequest", name, tool_name="Bash", tool_use_id="exec-1")
        self.assertEqual(again, asked)


if __name__ == "__main__":
    unittest.main()
