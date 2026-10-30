"""A Stop on a nudged harness records the background work it hands over.

A harness whose manifest says `[stop] enforce = "nudge"` runs no hooks/orchestrator-stop.sh, so
hooks/seat-state.sh writes its Stop, with the `holds` and `kind` that hook would have written, and
never over a prompt heard after it.  Where that hook runs, it stays the Stop's one writer.
Black-box: both hooks, beside the program `AK_BIN` names, run as a harness runs them in a Home of
tests/fixtures/akbin.py, judged by the fact they write (`hook-<seat>.json`); this test fails
against `/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import ROOT

SUBAGENT = {"id": "bg1", "type": "subagent", "status": "running", "description": "read acme"}
SHELL = {"id": "bg2", "type": "shell", "status": "running", "description": "sleep 600"}


class NudgedStopHoldsBackgroundWork(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def seat(self, model):
        self.home.write(".agentkit/state/session-acme.json",
                        {"orchestrator": model, "workers": [model], "reviewers": [model]})

    def stop(self, hook, *tasks):
        """That hook hears the seat's Stop handing over `tasks`: the fact standing, or None."""
        payload = {"hook_event_name": "Stop", "background_tasks": list(tasks),
                   "transcript_path": "", "last_assistant_message": "Started it."}
        done = self.home.run("bash", str(ROOT / "hooks" / hook), input=json.dumps(payload),
                             env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.err)
        fact = self.home.path / ".agentkit/state/hook-acme.json"
        return json.loads(fact.read_text()) if fact.exists() else None

    def test_a_nudged_stop_records_the_work_it_hands_over(self):
        self.seat("mimo")
        fact = self.stop("seat-state.sh", SUBAGENT, SHELL)
        self.assertEqual((fact["event"], fact["kind"], fact["holds"]),
                         ("Stop", "background", ["subagent", "shell"]))

    def test_a_nudged_stop_handing_over_nothing_holds_nothing(self):
        self.seat("mimo")
        self.stop("seat-state.sh", SUBAGENT, SHELL)
        fact = self.stop("seat-state.sh")
        self.assertEqual((fact["event"], fact["kind"]), ("Stop", ""))
        self.assertNotIn("holds", fact)

    def test_a_nudged_stop_written_late_never_replaces_a_prompt_heard_after_it(self):
        self.seat("mimo")
        # heard an hour from now: the Stop this hook hears now is the older fact
        later = {"session": "acme", "event": "UserPromptSubmit", "kind": "",
                 "text": "go on with acme", "at": time.time() + 3600}
        self.home.write(".agentkit/state/hook-acme.json", later)
        self.assertEqual(self.stop("seat-state.sh", SUBAGENT), later)

    def test_a_claude_stop_is_written_by_the_stop_hook_alone(self):
        self.seat("opus")
        self.assertIsNone(self.stop("seat-state.sh", SUBAGENT, SHELL))
        fact = self.stop("orchestrator-stop.sh", SUBAGENT, SHELL)
        self.assertEqual((fact["event"], fact["kind"], fact["holds"]),
                         ("Stop", "background", ["subagent", "shell"]))


if __name__ == "__main__":
    unittest.main()
