"""Every turn needs a recorded ending, including information-only answers.

Drive both native hooks against a throwaway HOME and fake records.
"""
from contextlib import contextmanager, ExitStack
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
from agentkit import config, stop, watch
from agentkit.told import heading

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "answer-seat"
REASON = ("You stopped without asking the user through the question prompt or ak notify needs, "
          "declaring done with ak notify done (--quiet for an information answer), "
          "or waiting on a run. Continue: decide the next step and do it.")
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
                "AGENTKIT_TMUX_SOCKET": "ak-test-answer", "TMUX_TMPDIR": str(self.home)}

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

    @contextmanager
    def local_config(self):
        with ExitStack() as stack:
            home = self.home / ".agentkit"
            for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
                stack.enter_context(patch.object(config, name,
                                    home if name == "HOME" else home / name.lower()))
            stack.enter_context(patch.object(config, "CODE", self.home / "code"))
            yield

    def read_as(self):
        """(state, event) a Claude seat's row reads off what its hooks have written down."""
        with patch.object(config, "STATE", self.state):
            return watch.hook_state("claude", watch.hook_facts(SEAT))[:2]

    def latch(self):
        return json.loads((self.state / f"stop-{SEAT}.json").read_text())

    def quiet(self, text=ANSWER):
        return subprocess.run([sys.executable, str(REPO / "bin/ak"), "notify", "done", text,
                               "--quiet"], capture_output=True, text=True,
                              env={**self.env(), "AK_NOTIFY_SINK": "dry-run"}, timeout=30)

    def test_questions_and_mixed_requests_require_explicit_completion(self):
        for opened in ("Which parser does it use?", "How does it work",
                       "What caused the schema failure? Fix it and ship the API.",
                       "Fix the parser", heading("acme-api", time.time()) + "Which parser?"):
            with self.subTest(opened=opened):
                self.setUp()
                self.prompt(opened)
                self.assertEqual(self.blocked(self.stop())["reason"], REASON)
                done = self.quiet()
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.stop(), "")
                self.prompt(opened)
                self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_renamed_seats_next_prompt_invalidates_the_quiet_answer_everywhere(self):
        self.prompt("Explain the parser")
        done = self.quiet()
        self.assertEqual(done.returncode, 0, done.stderr)
        renamed = "acme-schema"
        (self.state / f"seat-{SEAT}.json").rename(self.state / f"seat-{renamed}.json")
        (self.state / f"stop-{SEAT}.json").rename(self.state / f"stop-{renamed}.json")
        (self.state / f"session-{SEAT}.json").write_text(json.dumps({"renamed": renamed}))
        self.prompt("Fix the export")
        with self.local_config():
            word = watch.session_state(renamed, session={"name": renamed}, cfg={}, records=[],
                                       harness="claude", live={"state": "at_prompt"},
                                       auth_out={}, gh_out={}, token_out={})
        self.assertEqual(word["word"], "needs you")
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_quiet_command_cannot_finish_a_prompt_arriving_while_plan_checks_run(self):
        self.prompt("Explain the parser")
        with self.local_config(), patch.object(stop.plan, "require_done", side_effect=lambda _name:
                             (self.prompt("Fix the export"), set())[1]):
            stop.quiet_done(SEAT, ANSWER)
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_prompt_during_rename_retires_the_quiet_answer(self):
        self.prompt("Explain the parser")
        self.assertEqual(self.quiet().returncode, 0)
        renamed = "acme-schema"
        old_state = self.state / f"seat-{SEAT}.json"
        new_state = self.state / f"seat-{renamed}.json"
        replace = Path.replace
        prompted = []

        def move(path, target):
            if path == old_state and Path(target) == new_state:
                prompted.append(self.prompt("Fix the export"))
            return replace(path, target)

        with self.local_config(), patch.object(Path, "replace", new=move):
            config.rename_session(SEAT, renamed)
            self.assertTrue(prompted)
            word = watch.session_state(
                renamed, session={"name": renamed}, cfg={}, records=[], harness="claude",
                live={"state": "at_prompt"}, auth_out={}, gh_out={}, token_out={})
            self.assertNotEqual(word["word"], "done")
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_delayed_quiet_command_cannot_end_a_prompt_during_rename(self):
        turn = self.prompt("Explain the parser")
        self.assertEqual(self.quiet().returncode, 0)
        renamed = "acme-schema"
        old_state = self.state / f"seat-{SEAT}.json"
        new_state = self.state / f"seat-{renamed}.json"
        replace = Path.replace

        def move(path, target):
            if path == old_state and Path(target) == new_state:
                self.prompt("Fix the export")
            return replace(path, target)

        def checked(name):
            with patch.object(Path, "replace", new=move):
                config.rename_session(SEAT, renamed)
            return set()

        with self.local_config(), patch.object(stop.plan, "require_done", side_effect=checked), \
                patch.object(stop.time, "time", return_value=turn["turn"]):
            self.assertFalse(stop.quiet_done(SEAT, "Explained the old parser"))
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_delayed_quiet_command_keeps_the_newer_answer(self):
        for new_prompt in (False, True):
            with self.subTest(new_prompt=new_prompt):
                self.setUp()
                turn = self.prompt("Which parser does it use?")
                current_text = "The export uses the current schema."
                with self.local_config():
                    require_done = stop.plan.require_done

                    def slow_check(name):
                        proven = require_done(name)
                        current = (self.prompt("Which export format does it use?")
                                   if new_prompt else turn)
                        with patch.object(stop.plan, "require_done", require_done), \
                                patch.object(stop.time, "time", return_value=max(
                                    current["turn"], turn["turn"] + 1)):
                            stop.quiet_done(name, current_text)
                        self.assertEqual(self.stop(), "")
                        return proven

                    with patch.object(stop.plan, "require_done", side_effect=slow_check), \
                            patch.object(stop.time, "time", return_value=turn["turn"]):
                        stop.quiet_done(SEAT, "Explained the old parser")
                    ending, _ = stop.recorded_ending(SEAT)
                    self.assertIsNotNone(ending, "the newer answer still ends its turn")
                    self.assertEqual(ending["text"], current_text)
                self.assertEqual(self.stop(), "")

    def test_a_quiet_answer_cannot_complete_an_open_plan(self):
        self.prompt("What caused the schema failure? Fix it and ship the API.")
        (self.state / f"plan-{SEAT}.md").write_text(
            '- [ ] The API repair is live · your eye · acme · written 2026-01-01 12:00\n')
        done = self.quiet()
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((self.state / f"notify-{SEAT}.json").exists())
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_an_unreadable_answer_is_no_ending(self):
        for payload in ({}, {"transcript_path": str(self.home / "missing.jsonl")}):
            with self.subTest(payload=payload):
                self.prompt("Explain the parser")
                self.assertEqual(self.blocked(self.stop(said=None, **payload))["reason"], REASON)

    def test_quiet_completion_needs_no_readable_answer(self):
        self.prompt("Explain the parser")
        done = self.quiet()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.stop(said=None), "")

    def test_a_parked_run_holds_completion_and_keeps_the_existing_bound(self):
        self.prompt("Which parser does it use?")
        done = self.quiet()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.parked_exhausted()
        for _ in range(2):
            reason = self.blocked(self.stop())["reason"]
            self.assertIn("run parked-exhausted parked:", reason)
            self.assertIn("ak run resume parked-exhausted", reason)
        self.assertEqual(self.stop(), "")
        self.prompt("Decide the next step")
        self.assertIn("parked-exhausted", self.blocked(self.stop())["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
