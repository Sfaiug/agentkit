"""A seat's hooks lose no event when the host's clock steps back.

A seat's fact (`hook-<seat>.json`) is the event its hooks heard last, by the moment each was
heard, and a host's clock can step back a second or so as it is set right.  An event heard
just after such a step reads as heard before the one standing: the question going up, or the
Stop that ends the turn, is lost, and the row keeps saying what is no longer so.  Each is
written after the one before it, and once the host's clock is past the seat's last moment
again, an event's moment is the host's own.  Black-box: Claude's hooks as ak's adapter
registers them, fired as Claude fires them (tests/fixtures/hookdrive.py), each Python they
start reading the host's clock as this test sets it; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks, transcript

# What each Python a hook starts reads as the host's clock: $CLOCK.
CLOCK = "import os, time\ntime.time = lambda: float(os.environ['CLOCK'])\n"
QUESTION = {"tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which colour?"}]}}


class ClockStepsBack(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.hooks = Hooks(self.home)
        self.home.write(".agentkit/state/session-acme.json",
                        {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["opus"]})
        site = self.home.root / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(CLOCK)
        self.site = str(site)

    def fire(self, event, clock, **payload):
        """That event, the host's clock reading `clock`; the seat's fact after it."""
        fired = self.hooks.fire(event, payload, seat="acme",
                                env={"PYTHONPATH": self.site, "CLOCK": repr(clock)})
        self.assertEqual(fired.code, 0, fired.err)
        return json.loads((self.home.path / ".agentkit/state/hook-acme.json").read_text())

    def test_each_event_is_written_after_the_one_before_though_the_clock_stepped_back(self):
        prompted = self.fire("UserPromptSubmit", 1000.5, prompt="Paint it.", session_id="x")
        asked = self.fire("PermissionRequest", 1000.25, **QUESTION)
        self.assertEqual((asked["event"], asked["text"]), ("PermissionRequest", "Which colour?"))
        self.assertGreater(asked["at"], prompted["at"])
        # the Stop that hands over the work in flight, none, is the stop rule's to write
        said = transcript(self.home, "turn", "Painted.")
        stopped = self.fire("Stop", 1000.25, transcript_path=said, background_tasks=[])
        self.assertEqual(stopped["event"], "Stop")
        self.assertGreater(stopped["at"], asked["at"])
        again = self.fire("UserPromptSubmit", 1001.0, prompt="Again.", session_id="x")
        self.assertEqual((again["event"], again["at"]), ("UserPromptSubmit", 1001.0))


if __name__ == "__main__":
    unittest.main()
