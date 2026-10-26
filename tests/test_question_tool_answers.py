"""The owner's answer through the harness's own question tool answers the seat's standing
question, as their prompt does.

Offline: the real hook, Claude Code's PostToolUse payloads, fake tmux and a temporary HOME.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, notify, watch

SEAT = "acme"
QUESTION = "Which schema should acme use?"
# What Claude Code 2.1.292 hands PostToolUse as the owner answers, cut to the fields ak reads.
ASKED = {"tool_name": "AskUserQuestion", "tool_input": {
    "questions": [{"question": QUESTION, "header": "Schema",
                   "options": [{"label": "Red"}, {"label": "Blue"}]}],
    "answers": {QUESTION: "Red"}}}
# ... and what Codex hands it as the owner answers its Plan-mode question.
CODEX = {"tool_name": "request_user_input", "tool_use_id": "call_1",
         "tool_input": {"questions": [{"id": "schema", "question": QUESTION}]},
         "tool_response": {"answers": {"schema": {"answers": ["Red"]}}}}
PLAN = {"tool_name": "ExitPlanMode", "tool_input": {"plan": "# Plan: write hello.txt\n"}}

# No command falls through to the host's tmux.
FAKE_TMUX = r"""#!/bin/bash
[[ $1 = -L && $2 = agentkit-test ]] || exit 1
shift 2
case $1 in
  list-sessions) printf '%s\t%s\t100\t0\t1\n' acme "$HOME" ;;
  list-panes) printf 'acme\t0\n' ;;
  display-message) [[ $4 = %7 ]] && printf '/fake/agentkit-test\tacme\n' ;;
  capture-pane) cat "$FAKE_CAPTURE" ;;
  set-option) ;;
  *) exit 1 ;;
esac
"""

# The hook starts its look in the background: this records when it finished, and how.
PYTHON = r"""#!/bin/bash
if [[ $1 = -c && $2 = *watch.hook_look* ]]; then
  timeout -k 2 15 "$TEST_PYTHON" "$@"
  printf '%s\n' "$?" >"$LOOK_FINISHED"
else
  exec "$TEST_PYTHON" "$@"
fi
"""


class QuestionToolAnswers(Sandbox):
    def setUp(self):
        super().setUp()
        # the hook's own HOME and the readers here share these paths
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {"cwd": str(self.root)})
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, script in (("tmux", FAKE_TMUX), ("python3", PYTHON)):
            (self.bin / name).write_text(script)
            (self.bin / name).chmod(0o755)

    def hook(self, wait=True, **payload):
        self.finished = finished = self.root / "look-finished"
        finished.unlink(missing_ok=True)
        env = {"HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
               "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator",
               "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_NOTIFY_SINK": "dry-run",
               "TMUX": "/fake/agentkit-test,1,0", "TMUX_PANE": "%7",
               "FAKE_CAPTURE": str(REPO / "tests/fixtures/claude-prompt-pane.txt"),
               "TEST_PYTHON": sys.executable, "LOOK_FINISHED": str(finished)}
        done = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")], text=True,
                              input=json.dumps({"hook_event_name": "PostToolUse", **payload}),
                              capture_output=True, env=env, timeout=30)
        self.assertEqual((done.returncode, done.stderr, done.stdout), (0, "", ""))
        if wait:
            self.wait_look()

    def wait_look(self):
        deadline = time.monotonic() + 20
        while not (self.finished.exists() and self.finished.read_text()):
            self.assertLess(time.monotonic(), deadline, "the hook's look did not finish")
            time.sleep(0.01)
        self.assertEqual(self.finished.read_text().strip(), "0")

    def test_the_question_tools_answer_answers_the_standing_question(self):
        for payload in (ASKED, CODEX):
            with self.subTest(payload["tool_name"]):
                notify.record(SEAT, "needs", QUESTION)
                self.hook(**payload)
                self.assertIsNone(notify.last(SEAT))

    def test_a_plans_approval_answers_nothing(self):
        notify.record(SEAT, "needs", QUESTION)
        self.hook(**PLAN)
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)

    def test_a_sub_agents_question_tool_answers_nothing(self):
        notify.record(SEAT, "needs", QUESTION)
        self.hook(**ASKED, agent_id="agent-1", agent_type="general-purpose")
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)

    def test_a_question_asked_after_the_answer_stays_open(self):
        # the look waits on this lock, and the question goes up after the answer's moment
        with notify.session_lock(SEAT):
            self.hook(wait=False, **ASKED)
            notify.record(SEAT, "needs", QUESTION, time=watch.hook_facts(SEAT)["at"] + 1)
        self.wait_look()
        self.assertEqual(notify.last(SEAT)["text"], QUESTION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
