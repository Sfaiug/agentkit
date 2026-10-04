"""An answer ends a turn the owner opened with a question.

Offline and deterministic: hooks/seat-state.sh opens the turn and
hooks/orchestrator-stop.sh judges its end, both run as their harness runs them --
the hook's own JSON on stdin -- against fake records and a throwaway HOME, never
a real seat or ~/.agentkit. Only the last sentence of the opening prompt ending in `?` lets a plain
answer stand at once; the owner's other prompts get one nudge first. A run parked
undecided still holds it, and another session's message or a run's report opens no answer.
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

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "answer-seat"
REASON = ("You stopped without asking the user through the question prompt or ak notify needs, "
          "declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it.")
NUDGE = ("The user's prompt did not end on a question. If it asked for work, continue: decide "
         "the next step and do it. If it asked you to find something out and your reply "
         "answers it, stop again; an answer is never ak notify done.")
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
                "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}

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

    # --- the answer ----------------------------------------------------------

    def test_a_plain_answer_ends_a_turn_the_owner_opened_with_a_question(self):
        for opened in ("Which parser does it use?",
                       "Please explain. Which parser does it use?\n"):
            with self.subTest(opened=opened):
                self.setUp()
                latch = self.prompt(opened)
                self.assertTrue(latch["asked"])
                self.assertFalse(latch["peer"])
                self.assertEqual(self.stop(), "")
                self.assertEqual(self.latch()["blocks"], 0)

    def test_an_owners_instruction_gets_one_nudge_then_its_answer_stands(self):
        for opened in ("Merge the parser now", "Check the parser and find out which schema it reads"):
            with self.subTest(opened=opened):
                self.setUp()
                latch = self.prompt(opened)
                self.assertEqual((latch["asked"], latch["owner"]), (False, True))
                payload = {"transcript_path": str(self.transcript(ANSWER)),
                           "background_tasks": []}
                self.assertEqual(self.blocked(self.stop(said=None, **payload))["reason"], NUDGE)
                self.assertEqual(self.stop(said=None, stop_hook_active=True, **payload), "")
                self.stop(said=None, hook=SEAT_STATE, stop_hook_active=True, **payload)
                self.assertEqual(self.latch()["blocks"], 1)
                self.assertEqual(self.read_as(), ("at_prompt", "Stop"))

    def test_a_runs_report_is_judged_as_today(self):
        latch = self.prompt("<task-notification>acme run ended</task-notification>")
        self.assertEqual((latch["asked"], latch["owner"]), (False, False))
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)
        self.assertEqual(self.stop(), "")

    def test_an_earlier_question_does_not_exempt_a_final_instruction(self):
        for opened in ("Which parser does it use? Please explain.",
                       "Should it read JSON?\n\nBuild the parser.",
                       "The old prompt was: which schema? Now fix it."):
            with self.subTest(opened=opened):
                self.setUp()
                self.assertFalse(self.prompt(opened)["asked"])
                self.assertEqual(self.blocked(self.stop())["reason"], NUDGE)

    def test_a_urls_question_mark_is_no_question(self):
        for opened in ("See docs/guide.md?foo for the schema",
                       "See https://example.com/docs?a=b for the schema"):
            with self.subTest(opened=opened):
                self.setUp()
                latch = self.prompt(opened)
                self.assertFalse(latch["asked"])
                self.assertEqual(self.blocked(self.stop())["reason"], NUDGE)

    def test_an_answer_stands_on_claude_with_no_held_notice(self):
        self.prompt("Which parser does it use?")
        payload = {"transcript_path": str(self.transcript(ANSWER)),
                   "background_tasks": []}
        self.assertEqual(self.stop(said=None, **payload), "")
        self.stop(said=None, hook=SEAT_STATE, **payload)
        self.assertEqual(self.read_as(), ("at_prompt", "Stop"))
        self.assertEqual(self.latch()["blocks"], 0)

    # --- what still holds it ---------------------------------------------------

    def test_a_parked_run_holds_an_answer_as_it_holds_a_done(self):
        self.prompt("Which parser does it use?")
        self.assertEqual(self.stop(), "")       # no parked run: the answer stands
        self.parked_exhausted()
        self.prompt("Which parser does it use?")
        reason = self.blocked(self.stop())["reason"]
        self.assertIn("run parked-exhausted parked: ", reason)
        self.assertIn("ak run resume parked-exhausted", reason)
        # ... and the latch that says so is still the question's one on the second stop
        self.assertTrue(self.latch()["asked"])
        self.assertIn("parked-exhausted", self.blocked(self.stop())["reason"])
        self.assertEqual(self.stop(), "")       # the third stop stands, as it always did

    def test_a_peer_message_asking_is_not_the_owner_asking(self):
        peer = ('<cross-session-message from="acme-fix-api" to="answer-seat">'
                "Which parser should I use?\n</cross-session-message>")
        latch = self.prompt(peer)
        self.assertTrue(latch["peer"])
        self.assertFalse(latch["asked"])    # the message wrapper is not an owner's question
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)


if __name__ == "__main__":
    unittest.main(verbosity=2)
