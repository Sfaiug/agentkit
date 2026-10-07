"""Every answer records completion; question wording grants no stop exception.

Offline: real hooks and completion CLI against invented records in a temporary HOME.
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
from agentkit import config, watch
from agentkit.told import heading

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "answer-seat"
REASON = ("You stopped without asking the user through the question prompt or ak notify needs, "
          "declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it. "
          "For an information-only answer, record ak notify done --quiet.")
ANSWER = "The parser reads the schema at startup and caches it."
SPENT = "three rounds spent: split or re-scope the task"


class StopAnswer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-stop-answer-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)

    # --- the fixtures a turn is judged from ---------------------------------

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

    def parked_exhausted(self, name="parked-exhausted"):
        self.run_json(name, state="exhausted", started_at=time.time() - 9000,
                      finished_at=time.time() - 60, error=SPENT)

    # --- driving the hooks the way the harness does --------------------------

    def env(self):
        return {"PATH": os.environ["PATH"], "HOME": str(self.home),
                "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator",
                "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(self.home)}

    def prompt(self, text):
        """Open a turn through hooks/seat-state.sh, as the harness does on a prompt."""
        done = subprocess.run(["bash", str(SEAT_STATE)], text=True, capture_output=True,
                              input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                                "prompt": text}),
                              env={**self.env(), "IDLE_COMPACT_STATE": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.state / f"stop-{SEAT}.json").read_text())

    def stop(self, said=ANSWER, hook=HOOK, **payload):
        """One end-of-turn hook call; the answer is what the harness reads off stdout."""
        if said is not None and "transcript_path" not in payload:
            payload["transcript_path"] = str(self.transcript(said))
        payload.setdefault("hook_event_name", "Stop")
        payload.setdefault("session_id", "fake")
        done = subprocess.run(["bash", str(hook)], input=json.dumps(payload), text=True,
                              capture_output=True, env=self.env())
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def blocked(self, output):
        self.assertTrue(output.strip(), "the hook allowed the stop")
        return json.loads(output)

    def read_as(self):
        """(state, event) a Claude seat's row reads off what its hooks have written down."""
        with patch.object(config, "STATE", self.state):
            return watch.hook_state("claude", watch.hook_facts(SEAT))[:2]

    def latch(self):
        return json.loads((self.state / f"stop-{SEAT}.json").read_text())

    def complete_quietly(self):
        done = subprocess.run([sys.executable, str(REPO / "bin/ak"), "notify", "done",
                               "--quiet", ANSWER], capture_output=True, text=True,
                              env=self.env(), timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((done.stdout, done.stderr), ("", ""))

    def test_questions_and_mixed_requests_require_explicit_completion(self):
        for opened in ("Which parser does it use?",
                       "Why did it stop? Fix the parser and the notification.",
                       "how does the parser work",
                       "Merge the parser now",
                       heading("acme-fix-api", time.time()) + "Which parser should I use?"):
            with self.subTest(opened=opened):
                self.setUp()
                self.prompt(opened)
                self.assertEqual(self.blocked(self.stop())["reason"], REASON)
                self.complete_quietly()
                self.assertEqual(self.stop(), "")

    def test_legacy_question_flags_grant_no_exception_and_failed_corrections_ask(self):
        self.prompt("Why did it stop? Fix it.")
        path = self.state / f"stop-{SEAT}.json"
        path.write_text(json.dumps({**self.latch(), "asked": True, "peer": True,
                                    "blocks": 0}))
        for _ in range(2):
            self.assertEqual(self.blocked(self.stop())["reason"], REASON)
        self.assertEqual(self.stop(), "")
        notice = json.loads((self.state / f"notify-{SEAT}.json").read_text())
        self.assertEqual(notice["kind"], "needs")
        self.assertIn("cannot continue", notice["text"])

    def test_a_quiet_answer_leaves_claude_at_its_prompt_after_both_hooks(self):
        self.prompt("Which parser does it use?")
        self.complete_quietly()
        payload = {"transcript_path": str(self.transcript(ANSWER)), "background_tasks": []}
        self.assertEqual(self.stop(said=None, **payload), "")
        self.stop(said=None, hook=SEAT_STATE, **payload)
        self.assertEqual(self.read_as(), ("at_prompt", "Stop"))

    def test_a_quiet_answer_cannot_complete_an_open_plan(self):
        self.prompt("Why did it stop? Fix it.")
        (self.state / f"plan-{SEAT}.md").write_text(
            "- [ ] Parser fixed · your eye · acme · written 2026-10-07 12:00\n")
        done = subprocess.run([sys.executable, str(REPO / "bin/ak"), "notify", "done",
                               "--quiet", ANSWER], capture_output=True, text=True,
                              env=self.env(), timeout=30)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("plan line(s) still open", done.stderr)
        self.assertFalse((self.state / f"notify-{SEAT}.json").exists())
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_parked_run_holds_even_an_explicit_quiet_answer(self):
        self.prompt("Which parser does it use?")
        self.complete_quietly()
        self.parked_exhausted()
        for _ in range(2):
            self.assertIn("run parked-exhausted parked: ", self.blocked(self.stop())["reason"])
        self.assertEqual(self.stop(), "")
        notice = json.loads((self.state / f"notify-{SEAT}.json").read_text())
        self.assertEqual(notice["kind"], "needs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
