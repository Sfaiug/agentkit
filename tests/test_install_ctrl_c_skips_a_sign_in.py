"""Ctrl-C at GitHub's sign-in ends gh and lets install.sh finish.

Walked on 27 Nov 2026 on a fresh Debian install: `install.sh` runs
`gh auth login -p https -w` in a terminal, which waits at "Press Enter to open
github.com in your browser...".  A newcomer with no GitHub account presses
Ctrl-C there; without a trap around that command, the interrupt ends the whole
installer before ak is set up.

Offline: the real `install.sh --server` runs inside a user-namespaced read-only
filesystem view (`bwrap`) with `/etc/passwd` pointing at a temporary HOME so
`SANDBOX=0`, a pty of its own as controlling terminal, and fake host tools and
`gh` on PATH.  Nothing outside the temporary directory is read-write.
"""

import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
GH_PROMPT = "Press Enter to open github.com in your browser..."
GH_PENDING = "  gh login -- `gh auth login -p https -w`, so runs can push, open and merge PRs"

# Logged out: `auth status` fails; `auth login` records its PID and waits on
# stdin just as GitHub's CLI does, inheriting whatever SIGINT disposition
# install.sh handed it.
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_GH_LOG"
case "$1 $2" in
  "auth status") exit 1 ;;
  "auth login")
    printf '%s\\n' "$$" >"$FAKE_GH_PID.tmp"
    mv "$FAKE_GH_PID.tmp" "$FAKE_GH_PID"
    printf '%s ' "$FAKE_GH_PROMPT"
    IFS= read -r _
    exit 1
    ;;
  *) exit 0 ;;
esac
"""

# Inside bwrap, take the pty slave as this process's own controlling terminal
# so bwrap stays outside the pty's foreground process group and does not die
# when Ctrl-C is sent to the installer.
TRAMPOLINE = (
    "import fcntl, os, sys, termios; "
    "os.setsid(); "
    "fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
    "os.execvp(sys.argv[1], sys.argv[1:])"
)

# Real utilities install.sh, adapters hooks, and tools/machine.sh call.
# Only these are symlinked into the fixture PATH so no real harness binary
# installed on the host box can leak into the run.
SYSTEM_TOOLS = (
    "awk", "basename", "bash", "cat", "chmod", "cmp", "cp", "cut", "date",
    "dirname", "env", "find", "git", "grep", "head", "hostname", "id", "ln",
    "ls", "mkdir", "mktemp", "mv", "printf", "readlink", "rm", "sed", "sh",
    "sleep", "sort", "stat", "tail", "tr", "uname", "wc",
)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class InstallCtrlCSkipsGithubSignIn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-install-ctrl-c-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self.gh_log = self.root / "gh.log"
        self.gh_pid = self.root / "gh.pid"
        self.passwd = self.root / "passwd"
        self.passwd.write_text(
            f"acme:x:{os.getuid()}:{os.getgid()}:Fixture:{self.home}:/bin/sh\n"
        )

        # Standard utilities symlinked from the host.
        for name in SYSTEM_TOOLS:
            target = shutil.which(name)
            if target:
                (self.bindir / name).symlink_to(target)
        (self.bindir / "python3").symlink_to(sys.executable)

        # Fake host tools so section (2), browser, tmux, cron and host tuning
        # run offline, touch nothing outside HOME and finish quickly.
        self._fake("gh", FAKE_GH)
        self._fake("apt-get", "#!/bin/sh\nexit 0\n")
        self._fake("sudo", "#!/bin/sh\nexit 1\n")
        self._fake("dpkg", "#!/bin/sh\nexit 1\n")
        self._fake("node", "#!/bin/sh\necho v22.0.0\n")
        self._fake("tailscale", "#!/bin/sh\nexit 0\n")
        self._fake("tmux", "#!/bin/sh\nexit 1\n")
        self._fake("systemctl", "#!/bin/sh\nexit 1\n")
        self._fake("crontab", "#!/bin/sh\n[ \"$1\" = -l ] && exit 1; cat >/dev/null\n")
        for tool in ("mosh", "jq", "curl", "rsync", "bwrap", "chromium"):
            self._fake(tool, "#!/bin/sh\nexit 0\n")

    def _fake(self, name, body):
        path = self.bindir / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def _env(self):
        return {
            "HOME": str(self.home),
            "USER": "acme",
            "PATH": str(self.bindir),
            "TMPDIR": str(self.tmpdir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "FAKE_GH_LOG": str(self.gh_log),
            "FAKE_GH_PID": str(self.gh_pid),
            "FAKE_GH_PROMPT": GH_PROMPT,
            # Host sysctl/proc/systemd probes skipped even before sudo checks.
            "AK_CORE_PATTERN": str(self.root / "no-core-pattern"),
            "AK_SYS": str(self.root / "no-sys"),
            "AK_PROC_SWAPS": str(self.root / "no-swaps"),
            "AK_SYSTEMD_SYSTEM": str(self.root / "no-systemd"),
            "AK_PROC_SYS_VM": str(self.root / "no-vm"),
            "AK_INOTIFY_INSTANCES": str(self.root / "no-inotify"),
            "AK_LIMA_CIDATA": str(self.root / "no-lima"),
        }

    def _bwrap_prefix(self):
        return [
            shutil.which("bwrap"), "--unshare-user",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--ro-bind", str(REPO), str(REPO),
            "--bind", str(self.root), str(self.root),
            "--ro-bind", str(self.passwd), "/etc/passwd",
            "--",
        ]

    def _gh_calls(self):
        if not self.gh_log.exists():
            return []
        return self.gh_log.read_text().splitlines()

    def _run_pty(self, steps, timeout=30.0):
        """Run real install.sh --server on a pty, firing each (trigger, action) once in order."""
        master, slave = os.openpty()
        vintr = termios.tcgetattr(master)[6][termios.VINTR]
        if isinstance(vintr, int):
            vintr = bytes([vintr])
        cmd = [
            *self._bwrap_prefix(),
            sys.executable, "-c", TRAMPOLINE,
            str(self.bindir / "bash"), str(REPO / "install.sh"), "--server",
        ]
        proc = subprocess.Popen(
            cmd, stdin=slave, stdout=slave, stderr=slave, env=self._env(),
        )
        os.close(slave)
        out = bytearray()
        step_idx = 0
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    out += chunk
                    while step_idx < len(steps):
                        trigger, action = steps[step_idx]
                        if trigger.encode() not in out:
                            break
                        if callable(action):
                            action(master, vintr)
                        else:
                            os.write(master, vintr if action == "INTR" else action)
                        step_idx += 1
                elif proc.poll() is not None:
                    break
            else:
                proc.kill()
                self.fail(f"install.sh timed out (step {step_idx}/{len(steps)}):\n"
                          + out.decode("utf-8", "replace"))
            rc = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(os.tcgetpgrp(master), signal.SIGKILL)
                except OSError:
                    pass
                proc.kill()
                proc.wait()
            os.close(master)
        return rc, out.decode("utf-8", "replace")

    def test_ctrl_c_at_github_sign_in_ends_gh_and_install_finishes(self):
        seen_pid = []

        def interrupt_gh(master, vintr):
            pid = int(self.gh_pid.read_text().strip())
            self.assertTrue(_alive(pid), "gh should still be waiting before Ctrl-C")
            seen_pid.append(pid)
            os.write(master, vintr)

        rc, out = self._run_pty([
            ("Which subscription do you have", b"\x04"),
            (GH_PROMPT, interrupt_gh),
            ("Discord webhook URL for notifications", b"\n"),
            ("Discord user id to @mention", b"\n"),
        ])
        self.assertEqual(len(seen_pid), 1, out)
        self.assertFalse(_alive(seen_pid[0]), "gh must have ended on Ctrl-C")
        self.assertEqual(rc, 0, out)
        self.assertIn("auth login -p https -w", self._gh_calls())
        self.assertIn("note: gh auth login -p https -w did not finish", out)
        self.assertIn("summary: server;", out)
        self.assertIn(GH_PENDING, out)

    def test_ctrl_c_before_github_sign_in_ends_the_installer(self):
        rc, out = self._run_pty([
            ("Which subscription do you have", "INTR"),
        ])
        self.assertEqual(rc, 128 + signal.SIGINT, out)
        self.assertEqual(
            [c for c in self._gh_calls() if c.startswith("auth login")], [],
            f"gh auth login must not run after an earlier interrupt: {self._gh_calls()}",
        )
        self.assertNotIn("summary: server;", out)

    def test_ctrl_c_after_github_sign_in_ends_the_installer(self):
        seen_pid = []

        def interrupt_gh(master, vintr):
            seen_pid.append(int(self.gh_pid.read_text().strip()))
            os.write(master, vintr)

        rc, out = self._run_pty([
            ("Which subscription do you have", b"\x04"),
            (GH_PROMPT, interrupt_gh),
            ("Discord webhook URL for notifications", "INTR"),
        ])
        self.assertEqual(len(seen_pid), 1, out)
        self.assertFalse(_alive(seen_pid[0]), "gh must have ended on Ctrl-C")
        self.assertIn("Discord webhook URL for notifications", out)
        self.assertEqual(rc, 128 + signal.SIGINT, out)
        self.assertNotIn("summary: server;", out)

    def test_no_terminal_starts_no_github_sign_in(self):
        cmd = [
            *self._bwrap_prefix(),
            str(self.bindir / "bash"), str(REPO / "install.sh"), "--server",
        ]
        proc = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=self._env(), timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(
            [c for c in self._gh_calls() if c.startswith("auth login")], [],
        )
        self.assertIn("summary: server;", proc.stdout)
        self.assertIn(GH_PENDING, proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
