"""A seat's turn does not end while one of its own runs sits parked undecided.

Offline and deterministic: hooks/orchestrator-stop.sh is run as its harness runs it -- the
hook's own JSON on stdin -- against fake run records and a throwaway HOME, never a real seat
or ~/.agentkit.  Undecided is `run.unfinished` whole, the runs `ak notify done` refuses on,
so a run still going never holds the turn and an acknowledged or stopped one holds nothing;
a question, `ak notify needs`, background work and the third stop stand past a parked run as
they always did, while a done, a run going or an `ak wait` ends the turn only with none.
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
SEAT, OTHER = "park-seat", "other-seat"
RECOMMENDATION = "Here is my recommendation. Let me know if I should continue."
SPENT = "three rounds spent: split or re-scope the task"
REASON = ("You stopped without asking the user a question, declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it.")


class StopParked(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".stop-parked-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)
        self.turn = time.time() - 60
        self.latch(self.turn)

    # --- the fixtures a turn is judged from ---------------------------------

    def latch(self, turn, blocks=None):
        """What hooks/seat-state.sh leaves behind on UserPromptSubmit: this turn's start."""
        record = {"session": SEAT, "turn": turn, "blocks": 0 if blocks is None else blocks}
        (self.state / f"stop-{SEAT}.json").write_text(json.dumps(record) + "\n")

    def transcript(self, said):
        """A Claude Code transcript whose last assistant message is `said`."""
        path = self.home / "transcript.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "go"}},
                 {"type": "assistant", "isSidechain": False,
                  "message": {"role": "assistant", "content": [{"type": "text", "text": said}]}}]
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return path

    def notified(self, kind, when):
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "kind": kind, "text": "something", "time": when}) + "\n")

    def run_json(self, name, owner=SEAT, **fields):
        directory = self.runs / name
        directory.mkdir(exist_ok=True)
        (directory / "run.json").write_text(json.dumps(
            {"run_id": name, "launched_session": owner, **fields}) + "\n")

    def parked_exhausted(self, name="parked-exhausted", state="exhausted", error=SPENT,
                         **extra):
        """An exhausted run nothing will move: rounds spent, no window, no dead reviewer."""
        self.run_json(name, state=state, started_at=self.turn - 9000,
                      finished_at=self.turn - 60, error=error, **extra)

    # --- driving the hook the way the harness does --------------------------

    def stop(self, said=RECOMMENDATION, env=None, **payload):
        """One end-of-turn hook call; the answer is what the harness reads off stdout."""
        if said is not None and "transcript_path" not in payload:
            payload["transcript_path"] = str(self.transcript(said))
        payload.setdefault("hook_event_name", "Stop")
        payload.setdefault("session_id", "fake")
        environment = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                       "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}
        environment.update(env or {})
        done = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True,
                              capture_output=True, env=environment)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def blocked(self, output):
        self.assertTrue(output.strip(), "the hook allowed the stop")
        return json.loads(output)

    # --- the hold ------------------------------------------------------------

    def test_a_running_seat_with_an_undecided_exhausted_run_is_held_and_names_it(self):
        self.run_json("going-running", state="running", started_at=self.turn - 9000)
        self.parked_exhausted()
        reason = self.blocked(self.stop())["reason"]
        self.assertIn("run parked-exhausted parked: ", reason)
        self.assertIn(SPENT, reason)
        for option in ("ak run resume parked-exhausted",
                       "relaunch it split or on another model",
                       "ak run stop parked-exhausted", "ask the owner"):
            self.assertIn(option, reason)
        # ... and a second parked run is named beside the first
        self.run_json("parked-interrupted", state="interrupted",
                      started_at=self.turn - 9000, finished_at=self.turn - 60,
                      interruption_reason="the loop died mid-turn")
        self.latch(self.turn)
        reason = self.blocked(self.stop())["reason"]
        self.assertIn("run parked-exhausted parked: ", reason)
        self.assertIn("run parked-interrupted parked: the loop died mid-turn", reason)

    def test_an_acknowledged_or_stopped_run_holds_nothing(self):
        for label, extra in (
                ("acknowledged", {"recovery_acknowledged_at": time.time() - 30}),
                ("stopped", {"state": "stopped", "error": "stopped by the user"})):
            with self.subTest(label=label):
                self.setUp()
                self.run_json("going-running", state="running",
                              started_at=self.turn - 9000)
                self.parked_exhausted(**extra)
                self.assertEqual(self.stop(), "")

    def test_another_seats_parked_run_is_no_reason_to_hold(self):
        self.parked_exhausted(name="theirs-parked", owner=OTHER)
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_an_ak_wait_does_not_end_the_turn_while_a_run_sits_parked(self):
        (self.state / f"seat-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "wait": {"on": OTHER, "at": self.turn}}) + "\n")
        self.run_json("theirs-going", owner=OTHER, state="running",
                      started_at=self.turn - 9000)
        sockets = self.home / "sockets"
        sockets.mkdir(mode=0o700)
        env = {"AGENTKIT_TMUX_SOCKET": "agentkit-test-dead", "TMUX_TMPDIR": str(sockets)}
        self.assertEqual(self.stop(env=env), "")      # the wait holds, nothing parked
        self.parked_exhausted()
        self.latch(self.turn)
        self.assertIn("run parked-exhausted parked: ",
                      self.blocked(self.stop(env=env))["reason"])

    def test_a_done_recorded_this_turn_does_not_end_it_while_a_run_sits_parked(self):
        self.notified("done", self.turn + 1)
        self.assertEqual(self.stop(), "")             # no parked run: the done stands
        self.parked_exhausted()
        self.latch(self.turn)
        self.assertIn("run parked-exhausted parked: ",
                      self.blocked(self.stop())["reason"])

    # --- what stands past a parked run, as it always did ---------------------

    def test_a_question_ends_the_turn_parked_run_or_not(self):
        asked = "I found two options.\n\nWhich one do you want?"
        self.assertEqual(self.stop(asked), "")
        self.parked_exhausted()
        self.assertEqual(self.stop(asked), "")

    def test_needs_background_and_the_third_stop_stand_past_a_parked_run(self):
        self.parked_exhausted()
        self.notified("needs", self.turn + 1)
        self.assertEqual(self.stop(), "")
        self.latch(self.turn)
        (self.state / f"notify-{SEAT}.json").unlink()
        self.assertEqual(self.stop(background_tasks=[{"id": "task-1"}]), "")
        self.latch(self.turn)
        self.assertIn("parked-exhausted", self.blocked(self.stop())["reason"])
        self.assertIn("parked-exhausted", self.blocked(self.stop())["reason"])
        self.assertEqual(self.stop(), "")
        self.assertEqual(json.loads((self.state / f"stop-{SEAT}.json").read_text())["blocks"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
