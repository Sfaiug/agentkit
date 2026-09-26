"""A turn another session's message opened keeps the seat's standing done.

Offline and deterministic: hooks/seat-state.sh opens the turn and
hooks/orchestrator-stop.sh judges its end, both run as their harness runs them --
the hook's own JSON on stdin -- against fake notify records and a throwaway HOME,
never a real seat or ~/.agentkit.  Claude Code wraps such a message in
<cross-session-message>; the seat only acknowledges it, so a done declared before
the turn still tells -- unless `ak notify` dropped it, or a run sits parked.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "peer-seat"
REASON = ("You stopped without asking the user a question, declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it.")
ACK = "Noted -- nothing new on my side."      # the seat acknowledges the message and stops
PEER_PROMPT = ('<cross-session-message from="atlas-fix-api" to="peer-seat">'
               "Finished the parser; over to you.</cross-session-message>")
SPENT = "three rounds spent: split or re-scope the task"


class StopPeerTurn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".stop-peer-", dir=REPO)
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

    def prompt(self, text):
        """Open a turn through hooks/seat-state.sh, as the harness does on a prompt."""
        done = subprocess.run(["bash", str(SEAT_STATE)], text=True, capture_output=True,
                              input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                                "prompt": text}),
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

    # --- the standing done ----------------------------------------------------

    def test_a_peer_opened_turn_with_a_standing_undropped_done_is_not_held(self):
        self.notified("done", self.done_at)
        latch = self.prompt(PEER_PROMPT)
        self.assertTrue(latch["peer"])
        self.assertGreater(latch["turn"], self.done_at)   # the done predates the turn
        self.assertEqual(self.stop(), "")

    def test_an_owner_opened_turn_with_the_same_standing_done_is_held_as_today(self):
        """The owner, or a run's notice typed into the seat, answers the done: it tells nothing."""
        for opened in ("merge the parser now",
                       "run 20260101-0900-parser finished: PASS"):   # typed in, not wrapped
            with self.subTest(opened=opened):
                self.setUp()
                self.notified("done", self.done_at)
                latch = self.prompt(opened)
                self.assertFalse(latch["peer"])
                self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_peer_opened_turn_whose_last_done_was_dropped_is_held(self):
        self.notified("done", self.done_at, seen=True)    # `ak notify` dropped it
        latch = self.prompt(PEER_PROMPT)
        self.assertTrue(latch["peer"])
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)
        # ... and the latch that says so is still the peer's one on the second stop
        self.assertTrue(json.loads((self.state / f"stop-{SEAT}.json").read_text())["peer"])
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)
        self.assertEqual(self.stop(), "")     # the third stop stands, as it always did

    def test_a_peer_opened_turn_with_an_undecided_parked_run_is_held(self):
        self.notified("done", self.done_at)
        self.run_json("parked-exhausted", state="exhausted", started_at=self.done_at - 9000,
                      finished_at=self.done_at - 60, error=SPENT)
        self.prompt(PEER_PROMPT)
        reason = self.blocked(self.stop())["reason"]
        self.assertIn("run parked-exhausted parked: ", reason)
        self.assertIn("ak run resume parked-exhausted", reason)

    def test_a_peer_opened_turn_waiting_on_a_run_is_judged_as_today(self):
        """A run launched during the turn still counts as waiting, peer or not."""
        self.prompt(PEER_PROMPT)
        turn = json.loads((self.state / f"stop-{SEAT}.json").read_text())["turn"]
        self.run_json("fresh-run", state="done", started_at=turn + 5,
                      finished_at=turn + 6)
        self.assertEqual(self.stop(), "")
        self.assertTrue(json.loads((self.state / f"stop-{SEAT}.json").read_text())["peer"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
