"""Internal peer turns require their own recorded ending and never answer owner questions.

Drive the native hooks against fake records and a throwaway HOME.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import config
from agentkit.told import heading

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "peer-seat"
REASON = ("You stopped without asking the user through the question prompt or ak notify needs, "
          "declaring done with ak notify done (--quiet for an information answer), "
          "or waiting on a run. Continue: decide the next step and do it.")
ACK = "Noted -- nothing new on my side."      # the seat acknowledges the message and stops
SPENT = "three rounds spent: split or re-scope the task"
NEWS = "Finished the parser; over to you."
PEER_PROMPT = heading("acme-fix-api", time.time()) + NEWS


class StopPeerTurn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-stop-peer-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)
        self.done_at = time.time() - 600    # the done the seat declared before the turn

    # --- the fixtures a turn is judged from ---------------------------------

    def notified(self, kind, when, **extra):
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "kind": kind, "text": "shipped", "time": when,
             **extra}) + "\n")

    def transcript(self, said):
        """A Claude Code transcript whose last assistant message is `said`."""
        path = self.home / "transcript.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "go"}},
                 {"type": "assistant", "isSidechain": False,
                  "message": {"role": "assistant", "content": [{"type": "text",
                                                                "text": said}]}}]
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return path

    def run_json(self, name, **fields):
        directory = self.runs / name
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps(
            {"run_id": name, "launched_session": SEAT, **fields}) + "\n")

    # --- driving the hooks the way the harness does --------------------------

    def env(self):
        return {"PATH": os.environ["PATH"], "HOME": str(self.home),
                "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}

    def prompt(self, text, field="prompt"):
        """Open a turn through hooks/seat-state.sh, as the harness does on a prompt."""
        done = subprocess.run(["bash", str(SEAT_STATE)], text=True, capture_output=True,
                              input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                                field: text}),
                              env={**self.env(), "IDLE_COMPACT_STATE": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.state / f"stop-{SEAT}.json").read_text())

    def stop(self, said=ACK, **payload):
        """One end-of-turn hook call; the answer is what the harness reads off stdout."""
        if said is not None and "transcript_path" not in payload:
            payload["transcript_path"] = str(self.transcript(said))
        payload.setdefault("hook_event_name", "Stop")
        payload.setdefault("session_id", "fake")
        done = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True,
                              capture_output=True, env=self.env())
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def blocked(self, output):
        self.assertTrue(output.strip(), "the hook allowed the stop")
        return json.loads(output)

    def test_each_peer_turn_requires_its_own_completion(self):
        self.notified("done", self.done_at)
        for field in ("prompt", "message"):
            with self.subTest(field=field):
                latch = self.prompt(PEER_PROMPT, field)
                self.assertEqual(self.blocked(self.stop())["reason"], REASON)
                self.notified("done", latch["turn"] + 1, quiet=True)
                self.assertEqual(self.stop(), "")
                # The next peer turn cannot borrow this completion either.
                self.notified("done", self.done_at)

    def test_peer_input_never_answers_an_owner_question(self):
        self.notified("needs", self.done_at)
        self.prompt(PEER_PROMPT)
        self.assertEqual(self.stop(), "")
        notice = json.loads((self.state / f"notify-{SEAT}.json").read_text())
        self.assertNotIn("answered_at", notice)

    def test_a_peer_completion_retired_after_failure_holds_the_turn(self):
        latch = self.prompt(PEER_PROMPT)
        self.notified("done", latch["turn"] + 1, quiet=True, seen=True)
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_rename_keeps_parked_work_holding_a_peer_completion(self):
        latch = self.prompt(PEER_PROMPT)
        self.notified("done", latch["turn"] + 1, quiet=True)
        self.run_json("parked-exhausted", state="exhausted", started_at=self.done_at - 9000,
                      finished_at=self.done_at - 60, error=SPENT)
        with patch.object(config, "STATE", self.state), patch.object(config, "ensure_dirs"):
            config.rename_session(SEAT, "renamed-peer")
        self.assertIn("run parked-exhausted parked:", self.blocked(self.stop())["reason"])

    def test_peer_turns_wait_only_while_their_work_is_live(self):
        self.prompt(PEER_PROMPT)
        self.run_json("fresh-run", state="running", started_at=time.time())
        self.assertEqual(self.stop(), "")
        path = self.runs / "fresh-run/run.json"
        saved = json.loads(path.read_text())
        path.write_text(json.dumps({**saved, "state": "done", "finished_at": time.time()}))
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)


if __name__ == "__main__":
    unittest.main(verbosity=2)
