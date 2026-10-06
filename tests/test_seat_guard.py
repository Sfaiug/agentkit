"""A seat's harness refuses a shell command that would end another seat's tmux, and only that.

Offline: hooks/seat-guard.sh is run as Claude Code, Codex and Grok Build run it -- their shared
PreToolUse payload on stdin -- against a throwaway HOME holding two seat records and a fake
tmux that lists one server's sessions and resolves targets as tmux would.  No real tmux server
is asked or touched.
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
# The fake resolves a kill's target as tmux does: ids (`%`/`@`) and a marked target to another
# seat, a `:window`/`:pane` to the current session (this seat), and the `-L other` server's
# current session to another seat.  A missing `-t` asks for the current session.
TMUX = r"""#!/usr/bin/env bash
server=main; t=""; has_t=0; cmd=""
while [[ $# -gt 0 ]]; do
  case $1 in
    -L) [[ $2 == other ]] && server=other; shift 2 ;;
    -S) shift 2 ;;
    -t) has_t=1; t=$2; shift 2 ;;
    -F) shift 2 ;;
    -*) shift ;;
    *) [[ -z $cmd ]] && cmd=$1; shift ;;
  esac
done
case $cmd in
  list-sessions)
    if [[ $server == other ]]; then printf '$0\tother-seat\n'
    else printf '$0\tmine\n$1\tother-seat\n$2\tplain\n'; fi ;;
  display-message)
    if [[ $server == other ]]; then echo other-seat; exit 0; fi
    if [[ $has_t == 0 ]]; then echo mine; exit 0; fi
    case $t in
      %*|@*|'~'|'{marked}'|/dev/*) echo other-seat ;;
      :*) echo mine ;;
      *) echo "${t%%:*}" ;;
    esac ;;
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
           "tmux kill-session -t 'oth*'",
           "tmux ls; tmux kill-session -t other-seat",     # a kill after a shell `;`
           "tmux ls &&\ntmux kill-session -t other-seat",  # ... after `&&` and a newline
           "tmux -uL agentkit kill-session -t other-seat",   # a grouped boolean before -L
           "tmux -uS /tmp/x.sock kill-session -t other-seat",
           "tmux kill-window -t '~'",                      # the marked pane's seat
           "tmux kill-pane -t '{marked}'",
           "tmux kill-session -t /dev/pts/41")              # a client's tty, resolved by tmux
ALLOWED = ("tmux kill-session -t mine",
           "tmux kill-session -t plain",
           "tmux kill-session -t =other",                  # exactly `other`, and none is
           "tmux ls",
           "echo kill-session -t other-seat",
           "echo tmux kill-session -t other-seat",         # the text as an argument runs nothing
           "printf '%s\\n' 'tmux kill-session -t other-seat'",
           "rg 'tmux kill-server' README.md",
           "tmux kill-window -t :0",                        # a window of this seat's own session
           "tmux kill-pane -t :0.0",
           "tmux kill-session -C -t other-seat",            # -C clears alerts; the session lives
           "tmux kill-session -aC -t mine")


class SeatGuard(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit/state").mkdir(parents=True)
        for seat in ("mine", "other-seat"):
            (self.home / f".agentkit/state/session-{seat}.json").write_text("{}\n")
        (self.home / "bin").mkdir()
        self.tmux = self.home / "bin/tmux"
        self.tmux.write_text(TMUX)
        self.tmux.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("AK_RUN_ROLE", "AGENTKIT_SESSION")}
        self.env.update(HOME=str(self.home), AGENTKIT_SESSION="mine",
                        PATH=f"{self.home / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")

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

    def test_a_kill_on_the_remote_servers_current_session_is_refused(self):
        # a kill with no -t ends that server's current session, window or pane -- another seat.
        for command in ("tmux -L other kill-session", "tmux -L other kill-window",
                        "tmux -L other kill-pane"):
            with self.subTest(command=command):
                decision = json.loads(self.hook(command))["hookSpecificOutput"]
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertIn("other-seat", decision["permissionDecisionReason"])

    def test_a_seat_kills_its_own_tmux_after_a_rename(self):
        # ak orch rename leaves a pointer; the launch name in the env is the old one.
        (self.home / ".agentkit/state/session-mine.json").write_text(
            json.dumps({"renamed": "renamed-seat"}))
        (self.home / ".agentkit/state/session-renamed-seat.json").write_text("{}\n")
        self.tmux.write_text(TMUX.replace("\\tmine\\n", "\\trenamed-seat\\n"))
        for command in ("tmux kill-session -t renamed-seat", "tmux kill-window -t renamed-seat:0"):
            with self.subTest(command=command):
                self.assertEqual(self.hook(command), "")

    def test_only_a_seat_is_guarded_and_a_broken_payload_runs(self):
        kill = REFUSED[0]
        self.assertEqual(self.hook(kill, AK_RUN_ROLE="worker"), "")
        self.assertEqual(self.hook(kill, AGENTKIT_SESSION=""), "")
        self.assertEqual(self.hook("{ not json: tmux kill-server", raw=True), "")


if __name__ == "__main__":
    unittest.main()
