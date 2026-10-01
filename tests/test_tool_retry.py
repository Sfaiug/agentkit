"""Timeouts get one more try; a stop says why and names the command that carries on.

Offline: subprocess.run raises fake timeouts or returns canned answers; sleep is recorded.
"""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

COMMANDS = (["git", "fetch", "origin", "--prune"], ["gh", "api", "user"])
REFUSED = "fatal: could not read Username: terminal prompts disabled"
CFG = {"providers": {"acme": {}, "other": {}}, "models": {
    "build": {"harness": "fake", "model": "build", "effort": "low", "provider": "acme"},
    "review": {"harness": "fake", "model": "review", "effort": "low", "provider": "other"}}}


class ToolRetry(unittest.TestCase):
    def setUp(self):
        self.env = patch.object(config, "child_env", return_value={"ACME": "kept"})
        self.env.start()
        self.addCleanup(self.env.stop)
        context = patch.object(run._RUN_CONTEXT, "state", {"run_id": "fix-api"}, create=True)
        context.start()
        self.addCleanup(context.stop)

    def test_timeout_retries_the_same_call_after_a_short_pause(self):
        for cmd in COMMANDS:
            for timeout in (None, 3):
                with self.subTest(cmd=cmd, timeout=timeout):
                    events, calls = [], []

                    def attempt(command, **kwargs):
                        events.append("call")
                        calls.append((command, kwargs))
                        if len(calls) == 1:
                            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                        return subprocess.CompletedProcess(command, 0, "answered\n", "")

                    def pause(seconds):
                        self.assertTrue(0 < seconds <= 5)
                        events.append("pause")

                    with patch.object(run.subprocess, "run", side_effect=attempt), \
                            patch.object(run.time, "sleep", side_effect=pause):
                        self.assertEqual(run.tool_run(cmd, cwd=Path("acme"), timeout=timeout,
                                                      env={"EXTRA": "kept"}),
                                         (0, "answered\n", ""))
                    self.assertEqual(events, ["call", "pause", "call"])
                    self.assertEqual(calls[0], calls[1])
                    kwargs = calls[1][1]
                    self.assertEqual(kwargs["timeout"], run.TOOL_CAP if timeout is None else timeout)
                    self.assertEqual(kwargs["cwd"], "acme")
                    self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                    self.assertEqual(kwargs["env"], {"ACME": "kept", "EXTRA": "kept",
                                     "AGENTKIT_RUN": "fix-api", "GIT_TERMINAL_PROMPT": "0",
                                     "GH_PROMPT_DISABLED": "1"})

    def test_two_timeouts_stop_with_a_network_reason(self):
        for cmd in COMMANDS:
            with self.subTest(cmd=cmd), \
                    patch.object(run.subprocess, "run",
                                 side_effect=subprocess.TimeoutExpired(cmd, 3)) as attempt, \
                    patch.object(run.time, "sleep") as pause:
                code, out, err = run.tool_run(cmd, timeout=3)
                self.assertIsNone(code)
                self.assertEqual(out, "")
                self.assertEqual(attempt.call_count, 2)
                pause.assert_called_once()
                self.assertIn("was killed after 3s", err)
                self.assertIn("the remote did not answer", err)
                self.assertNotIn("gh auth status", err)
                self.assertNotIn("credential prompt", err)
                self.assertNotIn("resume", err)

    def test_a_refused_prompt_is_not_retried_even_after_a_timeout(self):
        for cmd, refusal in zip(COMMANDS, (REFUSED, "gh: prompts are disabled")):
            for timed_out in (False, True):
                with self.subTest(cmd=cmd, timed_out=timed_out):
                    answers = ([subprocess.TimeoutExpired(cmd, 3)] if timed_out else [])
                    answers.append(subprocess.CompletedProcess(cmd, 4, "", refusal))
                    with patch.object(run.subprocess, "run", side_effect=answers) as attempt, \
                            patch.object(run.time, "sleep") as pause:
                        code, _, err = run.tool_run(cmd, timeout=3)
                    self.assertEqual(code, 4)
                    self.assertEqual(attempt.call_count, 2 if timed_out else 1)
                    self.assertEqual(pause.call_count, int(timed_out))
                    self.assertTrue(run.stopped(code, err))
                    self.assertIn("gh auth status", err)
                    self.assertIn("remote's credentials", err)
                    self.assertNotIn("remote did not answer", err)
                    self.assertNotIn("resume", err)

    def test_an_ordinary_failure_is_returned_without_a_retry(self):
        for cmd in COMMANDS:
            with self.subTest(cmd=cmd), \
                    patch.object(run.subprocess, "run", return_value=
                                 subprocess.CompletedProcess(cmd, 1, "", "rejected")) as attempt, \
                    patch.object(run.time, "sleep") as pause:
                self.assertEqual(run.tool_run(cmd), (1, "", "rejected"))
                attempt.assert_called_once()
                pause.assert_not_called()

    def test_a_pass_with_stopped_delivery_names_its_merge_command(self):
        cmd = COMMANDS[0]
        for answer in (subprocess.TimeoutExpired(cmd, 3),
                       subprocess.CompletedProcess(cmd, 128, "", REFUSED)):
            with self.subTest(answer=answer), \
                    patch.object(run.subprocess, "run", side_effect=
                                 answer if isinstance(answer, Exception) else [answer]), \
                    patch.object(run.time, "sleep"):
                _, _, err = run.tool_run(cmd, timeout=3)
            state = {"run_id": "fix-api", "state": "pass", "verdict": "PASS", "repo": "acme",
                     "merge_failed": True, "merge_note": err, "executor": "build",
                     "reviewer": "review", "review": {"verdict": "PASS", "returncode": 0,
                     "done_when": True, "executor": "build", "reviewer": "review",
                     "executor_provider": "acme", "reviewer_provider": "other",
                     "head_sha": "1" * 40, "tree_sha": "2" * 40}}
            line = run.handback_line(state, REPO / "acme" / "fix-api", CFG)
            self.assertIn("PASS not merged", line)
            self.assertEqual(run.retry_command(state), "ak run merge fix-api")
            self.assertIn(run.retry_command(state), line)
            self.assertNotIn("resume", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
