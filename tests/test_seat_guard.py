"""A seat's harness refuses a shell command that would end another seat's tmux, and only that.

Offline: hooks/seat-guard.sh is run as Claude Code, Codex and Grok Build run it -- their shared
PreToolUse payload on stdin -- against a throwaway HOME holding two seat records and a fake
tmux that lists one server's sessions.  No real tmux server is asked or touched.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks/seat-guard.sh"
# `mine` and `other-seat` are seats ak keeps records of; `plain` is a tmux session nobody's seat.
TMUX = r"""#!/usr/bin/env bash
while [[ ${1:-} == -[LS] ]]; do shift 2; done
case ${1:-} in
  list-sessions) printf '$0\tmine\n$1\tother-seat\n$2\tplain\n' ;;
  display-message) [[ " $* " == *" -t %3 "* ]] && echo other-seat ;;
esac
exit 0
"""
REFUSED = ("tmux kill-session -t other-seat",
           "tmux kill-ses -t other",                       # tmux's unique prefixes, both
           "tmux -L agentkit kill-server",
           "bash -c 'tmux kill-window -t other-seat:1'",
           "cd /tmp && tmux killp -t %3",                  # a pane of another seat, by its id
           "tmux kill-session -a -t mine",                 # every session but this seat's
           "tmux kill-session -t '$1'",
           "tmux kill-session -t 'oth*'")
ALLOWED = ("tmux kill-session -t mine",
           "tmux kill-session -t plain",
           "tmux kill-session -t =other",                  # exactly `other`, and none is
           "tmux ls",
           "echo kill-session -t other-seat")


class SeatGuard(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        (home / ".agentkit/state").mkdir(parents=True)
        for seat in ("mine", "other-seat"):
            (home / f".agentkit/state/session-{seat}.json").write_text("{}\n")
        (home / "bin").mkdir()
        (home / "bin/tmux").write_text(TMUX)
        (home / "bin/tmux").chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("AK_RUN_ROLE", "AGENTKIT_SESSION")}
        self.env.update(HOME=str(home), AGENTKIT_SESSION="mine",
                        PATH=f"{home / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")

    def hook(self, command, **env):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "permission_mode": "bypassPermissions", "tool_input": {"command": command}}
        stdin = command if env.pop("raw", False) else json.dumps(payload)
        result = subprocess.run(["bash", str(HOOK)], input=stdin, capture_output=True,
                                text=True, timeout=30, env={**self.env, **env})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_ending_another_seat_is_refused_with_its_name(self):
        for command in REFUSED:
            with self.subTest(command=command):
                decision = json.loads(self.hook(command))["hookSpecificOutput"]
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertIn("other-seat", decision["permissionDecisionReason"])
                self.assertIn('ak tell other-seat', decision["permissionDecisionReason"])
                self.assertNotIn("plain", decision["permissionDecisionReason"])

    def test_its_own_seat_and_sessions_no_seat_owns_are_let_through(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command), "")

    def test_only_a_seat_is_guarded_and_a_broken_payload_runs(self):
        kill = REFUSED[0]
        self.assertEqual(self.hook(kill, AK_RUN_ROLE="worker"), "")
        self.assertEqual(self.hook(kill, AGENTKIT_SESSION=""), "")
        self.assertEqual(self.hook("{ not json: tmux kill-server", raw=True), "")


if __name__ == "__main__":
    unittest.main()
