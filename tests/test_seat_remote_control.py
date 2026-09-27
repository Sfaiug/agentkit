"""Every Claude seat starts with Remote Control on, named after the seat; workers never do.

Offline: the real adapters/claude.sh against a temporary HOME with a fake `claude` on PATH;
no harness, no network, and nothing outside that HOME is touched.
"""

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/claude.sh"
SEAT = "lagoon"
ACCOUNT = "quay"
CONVERSATION = "9f3a7c1e-2b4d-4e6f-8a0c-1d2e3f4a5b6c"


class SeatRemoteControl(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-seat-remote-control-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.args_file = self.root / "claude-args.txt"
        # A `claude` that records what the worker turn was given and answers one event.
        (self.bin / "claude").write_text(
            "#!/usr/bin/env bash\n"
            f"printf '%s\\n' \"$@\" >{shlex.quote(str(self.args_file))}\n"
            "cat >/dev/null || true\n"
            "printf '{\"type\":\"result\",\"result\":\"ok\",\"session_id\":\"fake-sid\"}\\n'\n")
        (self.bin / "claude").chmod(0o755)

    def env(self, account=None, seat=SEAT):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")}
        env.update(HOME=str(self.root), PATH=f"{self.bin}{os.pathsep}{env.get('PATH', '')}",
                   AGENTKIT_SESSION=seat,
                   AGENTKIT_ACCOUNT="" if account is None else account)
        return env

    def interactive(self, *args, account=None):
        proc = subprocess.run([str(ADAPTER), "interactive", "opus", "medium", *args],
                              capture_output=True, text=True, env=self.env(account))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return shlex.split(proc.stdout)

    def claude_tail(self, words):
        """The TUI invocation: the words after the last `--`, starting with `claude`."""
        seps = [i for i, word in enumerate(words) if word == "--"]
        tail = words[seps[-1] + 1:] if seps else words
        self.assertEqual(tail[0], "claude", words)
        return tail

    def test_seat_command_carries_remote_control_named_after_the_seat(self):
        for account in (None, ACCOUNT):
            for kind, extra in (("new", [CONVERSATION, "new"]),
                                ("resume", [CONVERSATION])):
                with self.subTest(account=account or "usual", kind=kind):
                    tail = self.claude_tail(self.interactive(*extra, account=account))
                    self.assertIn("--remote-control", tail)
                    self.assertEqual(tail[tail.index("--remote-control") + 1], SEAT)
                    if kind == "new":
                        self.assertEqual(tail[tail.index("--session-id") + 1], CONVERSATION)
                    else:
                        self.assertEqual(tail[tail.index("--resume") + 1], CONVERSATION)

    def test_worker_turn_carries_no_remote_control(self):
        # A worker is seatless, but even with the seat's name around the turn must not
        # take it: the run verb never reads it.
        for account in (None, ACCOUNT):
            for sid in (None, CONVERSATION):
                with self.subTest(account=account or "usual",
                                  sid="resume" if sid else "fresh"):
                    ws = self.root / f"ws-{account or 'usual'}-{sid is not None}"
                    ws.mkdir(exist_ok=True)
                    prompt = ws / "prompt.md"
                    prompt.write_text("Say ok.\n")
                    out = ws / "out"
                    cmd = [str(ADAPTER), "run", "opus", "medium",
                           str(ws), str(prompt), str(out)]
                    if sid:
                        cmd.append(sid)
                    proc = subprocess.run(cmd, capture_output=True, text=True,
                                          env=self.env(account))
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    args = self.args_file.read_text().splitlines()
                    self.assertNotIn("--remote-control", args)
                    self.assertIn("--model", args)


if __name__ == "__main__":
    unittest.main()
