"""A new user's GitHub login at install asks nothing but the one-time code.

A bare `gh auth login` asks host, protocol, git and browser-or-token before the code;
`gh auth login -p https -w` answers all four.  With a terminal, section (3) runs gh with
exactly those flags; without one, its note and the closing pending line name that command.

Offline: section (3) and the pending section of the real install.sh, with install.sh's own
GH_LOGIN line, run against a logged-out fake `gh` on a fixture PATH.
"""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
COMMAND = "gh auth login -p https -w"

# Logged out: `auth status` fails, anything else succeeds; each call's arguments logged.
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_GH_LOG"
[ "$1 $2" != "auth status" ]
"""


class InstallGithubLogin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-install-gh-login-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self.home = self.root / "home"
        (self.home / ".agentkit" / "secrets").mkdir(parents=True)
        (self.root / "repo" / "adapters").mkdir(parents=True)
        self.log = self.root / "gh.log"
        gh = self.bindir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        # the pending section's expiry arithmetic and count; nothing else on PATH
        for tool in ("stat", "date", "grep"):
            (self.bindir / tool).symlink_to(shutil.which(tool))

    def run_slice(self, start, end, tty):
        source = (REPO / "install.sh").read_text()
        definition = next(line for line in source.splitlines() if line.startswith("GH_LOGIN="))
        begin = source.index(start)
        block = source[begin:] if end is None else source[begin:source.index(end, begin + 1)]
        script = (
            "set -euo pipefail\n"
            f"REPO={shlex.quote(str(self.root / 'repo'))}\n"
            f"AK={shlex.quote(str(self.home / '.agentkit'))}\n"
            f"ROLE=server\nSANDBOX=0\nALIAS=\nOS=Linux\nTTY={tty}\n"
            "have() { command -v \"$1\" >/dev/null 2>&1; }\n"
            "note() { echo \"note: $*\" >&2; }\n"
            f"{definition}\n{block}")
        proc = subprocess.run(
            [shutil.which("bash"), "-c", script], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, cwd=str(self.root),
            env={**os.environ, "HOME": str(self.home), "PATH": str(self.bindir),
                 "FAKE_GH_LOG": str(self.log)})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def harnesses(self, tty):
        return self.run_slice("# --- (3) the harnesses", "\n# --- (3b)", tty)

    def logins(self):
        return [call for call in self.log.read_text().splitlines()
                if call.startswith("auth login")]

    def test_a_terminal_runs_gh_with_every_question_answered(self):
        self.harnesses(tty=1)
        self.assertEqual(self.logins(), [COMMAND.removeprefix("gh ")])

    def test_no_terminal_names_the_same_command_in_the_note_and_the_pending_line(self):
        proc = self.harnesses(tty=0)
        self.assertEqual(self.logins(), [])
        self.assertIn(f"run `{COMMAND}` so runs can push", proc.stderr)
        proc = self.run_slice("# --- (i) what this run could not do", None, 0)
        self.assertIn(f"  gh login -- `{COMMAND}`, so runs can push", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
