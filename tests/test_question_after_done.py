"""A seat whose plan is done asks the owner nothing until they write to it again.

Offline and deterministic: hooks/orchestrator-stop.sh is run as Claude Code runs it, before its
question prompt goes up (PreToolUse) and at a turn's end (Stop), with the hook's own JSON on
stdin, against a throwaway HOME, fake plans and run records, and the owner's message times
handed to the hook's Python by a sitecustomize.  No harness, no network and nothing of the
owner's is touched.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT = "done-seat"
DONE = "- [x] the parser parses · check: `true` · acme · written 2026-10-09 12:00 · done 0123456789ab\n"
OWED = "- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n"
QUESTION = "The parser is live and checked. Can I mark this done?"
ASKED = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "session_id": "fake",
         "tool_input": {"questions": [{"question": QUESTION, "header": "Done", "multiSelect": False,
                                       "options": [{"label": "Yes", "description": "It is done"},
                                                   {"label": "No", "description": "Not yet"}]}]}}


class QuestionAfterDone(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-question-after-done-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)
        self.plan(DONE)
        self.owner_wrote(-3600)     # the prompt the job began with

    # --- the fixtures a question is judged from -----------------------------

    def plan(self, text):
        """The seat's plan, last written ten minutes ago: when its last line was ticked."""
        path = self.state / f"plan-{SEAT}.md"
        path.write_text(text)
        self.done_at = time.time() - 600
        os.utime(path, (self.done_at, self.done_at))

    def owner_wrote(self, *since_done):
        """The owner's messages in the seat's conversation, in seconds after the plan's last
        write, as `notify.owner_said` reads them out of it."""
        times = sorted(self.done_at + each for each in since_done)
        (self.home / "sitecustomize.py").write_text(
            "from agentkit import notify\n"
            f"notify.owner_said = lambda name, seat=None: {times!r}\n")

    def parked(self):
        """An exhausted run of the seat's that nothing will move: rounds spent, undecided."""
        directory = self.runs / "parked-exhausted"
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps(
            {"run_id": "parked-exhausted", "launched_session": SEAT, "state": "exhausted",
             "started_at": time.time() - 9000, "finished_at": time.time() - 120,
             "error": "three rounds spent: split or re-scope the task"}) + "\n")

    def transcript(self, said):
        path = self.home / "transcript.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "go"}},
                 {"type": "assistant", "isSidechain": False,
                  "message": {"role": "assistant", "content": [{"type": "text", "text": said}]}}]
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return path

    # --- driving the hook the way Claude Code does --------------------------

    def started(self, command, stdin="", env=None):
        environment = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                       "PYTHONPATH": f"{self.home}:{REPO}", "AK_NOTIFY_SINK": "off",
                       "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator", **(env or {})}
        return subprocess.run(command, input=stdin, text=True, capture_output=True,
                              env=environment, timeout=30)

    def hook(self, payload, env=None):
        done = self.started(["bash", str(HOOK)], json.dumps(payload), env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def refused(self, answer):
        self.assertIsNotNone(answer, "the question went up")
        decided = answer["hookSpecificOutput"]
        self.assertEqual((decided["hookEventName"], decided["permissionDecision"]),
                         ("PreToolUse", "deny"))
        return decided["permissionDecisionReason"]

    def stop(self, said):
        (self.state / f"stop-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "turn": time.time() - 60, "blocks": 0}) + "\n")
        return self.hook({"hook_event_name": "Stop", "session_id": "fake",
                          "transcript_path": str(self.transcript(said))})

    # --- the question -------------------------------------------------------

    def test_a_question_from_a_seat_whose_plan_is_done_is_refused_before_it_goes_up(self):
        reason = self.refused(self.hook(ASKED))
        self.assertIn("plan is done", reason)
        self.assertIn("last message", reason)
        # refused before it was drawn: nothing says the seat asked anything
        self.assertFalse((self.state / f"notify-{SEAT}.json").exists())

    def test_the_owner_writing_since_the_plan_was_done_lets_the_seat_ask_again(self):
        self.owner_wrote(-3600, 60)
        self.assertIsNone(self.hook(ASKED))

    def test_a_seat_still_owing_a_line_or_with_nothing_done_asks(self):
        self.plan(OWED)
        self.assertIsNone(self.hook(ASKED))
        (self.state / f"plan-{SEAT}.md").unlink()
        self.assertIsNone(self.hook(ASKED))

    def test_a_run_of_its_own_parked_undecided_lets_the_seat_ask(self):
        self.parked()
        self.assertIsNone(self.hook(ASKED))
        # past the name it owes too, which holds every other ending
        (self.state / f"session-{SEAT}.json").write_text(json.dumps(
            {"orchestrator": "opus", "workers": [], "cwd": str(self.home), "unnamed": True}))
        self.assertIsNone(self.hook(ASKED))

    def test_its_own_ak_notify_needs_is_refused_too(self):
        done = self.started([str(REPO / "bin/ak"), "notify", "needs", QUESTION])
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("plan is done", done.stderr)
        self.assertFalse((self.state / f"notify-{SEAT}.json").exists())

    def test_a_worker_is_never_refused(self):
        self.assertIsNone(self.hook(ASKED, env={"AK_RUN_ROLE": "worker"}))

    # --- the same question left in prose ------------------------------------

    def test_a_turn_ending_on_it_in_prose_stands_and_goes_back_once_the_owner_wrote(self):
        self.assertIsNone(self.stop(QUESTION))
        self.owner_wrote(-3600, 60)
        self.assertIn("question prompt", self.stop(QUESTION)["reason"])


if __name__ == "__main__":
    unittest.main()
