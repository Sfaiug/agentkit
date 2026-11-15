"""A turn's end is judged by a function any process can call, not only by the stop hook's own Python.

`turn_end.judge` takes a seat's launch name and its harness's Stop, and answers what
hooks/orchestrator-stop.sh prints; a caller that already holds the runs hands them in.
Offline: a fixture seat in a temporary HOME, its turn's latch, plan and transcript as
tests/test_stop_hook.py builds them, judged in this process.
"""

import json
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, record, turn_end

SEAT = "fix-api"
TURN = 9000         # the sandbox's clock reads 10000: the turn began before it
OWED = "- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n"
RUN = {"run_id": "acme-parser", "launched_session": SEAT, "state": "running",
       "started_at": TURN - 9000}


class TurnEndJudgedInProcess(Sandbox):
    def setUp(self):
        super().setUp()
        # what hooks/seat-state.sh leaves on UserPromptSubmit, and a plan line the seat owes
        (config.STATE / f"stop-{SEAT}.json").write_text(
            json.dumps({"session": SEAT, "turn": TURN, "blocks": 0}) + "\n")
        (config.STATE / f"plan-{SEAT}.md").write_text(OWED)

    def stop(self, said, records=None):
        """The seat's Stop on a Claude Code transcript whose last message is `said`."""
        transcript = self.root / "transcript.jsonl"
        transcript.write_text("".join(json.dumps(line) + "\n" for line in (
            {"type": "user", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": said}]}})))
        return turn_end.judge(SEAT, json.dumps({"hook_event_name": "Stop", "session_id": "fake",
                                                "transcript_path": str(transcript)}), records)

    def test_an_open_plan_line_with_nothing_recorded_is_sent_back(self):
        self.assertEqual(json.loads(self.stop("Here is my recommendation.")),
                         {"decision": "block", "reason": turn_end.REASON})

    def test_a_turn_waiting_on_a_run_ends(self):
        # on the runs its caller holds, none of them on disk
        self.assertEqual(self.stop("Waiting on run acme-parser.",
                                   records=[(config.RUNS / RUN["run_id"], RUN)]), "")
        # and on those it reads itself where none are given
        (config.RUNS / RUN["run_id"]).mkdir()
        record.save_state(config.RUNS / RUN["run_id"], RUN)
        self.assertEqual(self.stop("Waiting on run acme-parser."), "")


if __name__ == "__main__":
    unittest.main()
