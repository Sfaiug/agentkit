"""The start update runs behind the real menu: steps fill its rule while held steps leave keys
answering, and an exec takes the new code and the highlight only on the main screen. A name field
keeps its draft until Esc. Leaving the menu leaves the detached update to finish.

Offline: each HOME and git clone lives in an in-checkout sandbox, with a bare origin ahead,
the actual Python modules committed there, a fake install.sh and a git wrapper holding each
step until the test lets it go. Only the test's own children are signalled; seats, maintenance,
boot resume, the bridge and usage probes are fakes. The loop, draws, keys and exec are real.
"""

import fcntl
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import update

GIT = shutil.which("git")
INSTALL = '''#!/bin/sh
d="$(dirname "$0")/.."
echo installed >>"$d/installs"
touch "$d/install.started"
while [ -e "$d/install.hold" ]; do sleep 0.01; done
touch "$d/install.finished"
'''
GATED_GIT = '''#!/bin/sh
case "$3" in
  ls-remote|fetch|merge)
    touch "$HOME/$3.started"
    while [ -e "$HOME/$3.hold" ]; do sleep 0.01; done
    [ ! -e "$HOME/$3.fail" ] || { echo "fixture $3 failed" >&2; exit 7; }
    ;;
esac
exec "$START_GIT" "$@"
'''
CHILD = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "agentkit"))
# Load the listing's run helpers before the clock starts, as the other loop fixtures do.
from agentkit import BUILD, config, macbridge, menu, orch, run, terminal, watch

cfg = {"defaults": {"orchestrator": "acme", "workers": ["acme"]},
       "models": {"acme": {"harness": "claude", "model": "acme-model",
                           "provider": "anthropic"}}, "providers": {"anthropic": {}}}
config.load = lambda *args, **_kw: cfg
config.server_alias = lambda: "acme-server" if os.environ.get("START_CLIENT") else None
orch.listing = lambda *args, **_kw: [
    {"name": name, "repo": None, "path": "/", "created": 0}
    for name in ("fix-api", "tidy-docs", "web-portal")]
orch.file_projectless = lambda *args, **_kw: None
orch.taken_names = lambda: set()
orch.job_notices = lambda: []
menu.run_records = lambda *args, **_kw: []
menu.seat_row_state = lambda *args, **_kw: {"word": "working", "reason": "", "since": None}
menu.seat_progress = lambda *args, **_kw: (0, 0)
menu.usage_lines = lambda *args, **_kw: []
menu.Live.probe = lambda *args, **_kw: False
terminal.sense = lambda: None

def parent(name):
    print(f"<{name} {os.getpid()}>", flush=True)
watch.resume_after_boot = lambda *args, **_kw: parent("boot")
orch.maintenance = lambda *args, **_kw: parent("maintenance")
macbridge.start_background = lambda: parent("bridge")
real_draw, real_update = menu.draw, menu.update_first

def draw(*args, **kwargs):
    result = real_draw(*args, **kwargs)
    drawn = kwargs.get("drawn", args[5] if len(args) > 5 else None)
    print(f"<draw {BUILD} {drawn['cursor'] if drawn else ''}>", flush=True)
    return result

def update_first(*args, **kwargs):
    proc = real_update(*args, **kwargs)
    if proc:
        with (Path.home() / "updaters").open("a") as out:
            out.write(f"{proc.pid}\n")
        print(f"<updater {proc.pid} {os.getpgid(proc.pid)}>", flush=True)
    return proc

menu.draw, menu.update_first = draw, update_first
print(f"<start {BUILD}>", flush=True)
print("<begin>", flush=True)
code = menu.main(sys.argv[1:])
print("<exit>", flush=True)
sys.exit(code)
'''
INHERITED = ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR", "AK_RUN_ROLE",
             "AGENTKIT_SESSION", "TMUX", "NO_COLOR", "COLUMNS", "LINES", "PYTHONPATH",
             "AK_MENU_CURSOR")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def running(pid):
    """Whether this test's recorded child is still running (an orphan can already be a zombie)."""
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        return sys.platform != "linux" or stat.read_text().split(") ", 1)[1][0] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        return False


class Screen:
    def __init__(self, case, *flags):
        self.case, self.output = case, b""
        self.lock = threading.Lock()
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 90, 0, 0))
        self.proc = subprocess.Popen([sys.executable, str(case.child), *flags],
                                     stdin=self.slave, stdout=self.slave, stderr=self.slave,
                                     env=case.env, cwd=case.root, start_new_session=True)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        case.addCleanup(self.close)

    def read(self):
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            with self.lock:
                self.output += chunk

    def text(self):
        with self.lock:
            return self.output.decode("utf-8", "replace")

    def when(self, pattern, after=0, timeout=10):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            with self.lock:
                found = re.search(pattern.encode(), self.output[after:])
                if found:
                    return found
            time.sleep(0.002)
        self.case.fail(f"never saw {pattern!r}:\n{self.text()[-4000:]}")

    def key(self, key, pattern):
        with self.lock:
            after = len(self.output)
        os.write(self.master, key)
        self.when(pattern, after)

    def leave(self):
        self.key(b"\x1b", "<exit>")
        self.case.assertEqual(self.proc.wait(10), 0, self.text())

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(10)
        for fd in (self.master, self.slave):
            os.close(fd)
        self.reader.join(5)


class StartUpdate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-start-update-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        self.env.update({"HOME": str(self.root), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                         "TERM": "xterm-256color", "GIT_CONFIG_NOSYSTEM": "1",
                         "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
                         "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                         "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                         "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "START_GIT": GIT,
                         "PYTHONDONTWRITEBYTECODE": "1"})
        self.origin, self.seed, self.clone = (self.root / name
                                              for name in ("origin.git", "seed", "agentkit"))
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.root, "clone", "-q", str(self.origin), str(self.seed))
        shutil.copytree(REPO / "agentkit", self.seed / "agentkit",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # Held steps end by release, so host scheduling cannot expire origin before a key.
        # The real origin timeout is checked separately with a controlled expiry.
        source = self.seed / "agentkit" / "update.py"
        source.write_text(source.read_text() + "\nbehind.__defaults__ = (None,)\n")
        (self.seed / "install.sh").write_text(INSTALL)
        (self.seed / "install.sh").chmod(0o755)
        self.first = self.merge("old")
        self.git(self.root, "clone", "-q", str(self.origin), str(self.clone))
        self.new = self.merge("new")
        self.child = self.root / "child.py"
        self.child.write_text(CHILD)
        tools = self.root / "tools"
        tools.mkdir()
        for name, body in (("git", GATED_GIT), ("ssh", '''#!/bin/sh
echo '<connected>'
while [ -e "$HOME/ssh.hold" ]; do sleep 0.01; done
''')):
            (tools / name).write_text(body)
            (tools / name).chmod(0o755)
        self.env["PATH"] = str(tools) + os.pathsep + self.env["PATH"]
        for step in ("ls-remote", "fetch", "merge", "install"):
            (self.root / f"{step}.hold").touch()
        self.addCleanup(self.finish_updates)

    def git(self, where, *args):
        return subprocess.run([GIT, "-C", str(where), *args], check=True, capture_output=True,
                              text=True, timeout=60, env=self.env).stdout.strip()

    def merge(self, build):
        (self.seed / "agentkit/__init__.py").write_text(f"BUILD = {build!r}\n")
        self.git(self.seed, "add", "-A")
        self.git(self.seed, "commit", "-q", "-m", build)
        self.git(self.seed, "push", "-q", "origin", "main")
        return self.git(self.seed, "rev-parse", "HEAD")

    def release(self, *steps):
        for step in steps:
            (self.root / f"{step}.hold").unlink(missing_ok=True)

    def wait_for(self, predicate, timeout=10):
        until = time.monotonic() + timeout
        while not predicate() and time.monotonic() < until:
            time.sleep(0.005)
        self.assertTrue(predicate())

    def updaters(self):
        path = self.root / "updaters"
        return [int(pid) for pid in path.read_text().splitlines()] if path.exists() else []

    def finish_updates(self):
        for path in self.root.glob("*.hold"):
            path.unlink(missing_ok=True)
        until = time.monotonic() + 5
        while any(running(pid) for pid in self.updaters()) and time.monotonic() < until:
            time.sleep(0.01)
        for pid in self.updaters():
            if running(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)    # only a child recorded in this test's HOME
                except ProcessLookupError:
                    continue
                self.fail(f"fixture updater {pid} did not finish")

    def installs(self):
        path = self.root / "installs"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def opened(self, *flags):
        screen = Screen(self, *flags)
        screen.when("<draw old fix-api>")
        return screen

    def test_steps_fill_while_keys_answer_then_exec_keeps_the_highlight(self):
        screen = self.opened()
        screen.key(b"\x1b[B", "<draw old tidy-docs>")     # origin is still being asked
        self.release("ls-remote")
        for step, done, key, seat in (("fetch", 0, b"\x1b[B", "web-portal"),
                                      ("merge", 1, b"\x1b[A", "tidy-docs"),
                                      ("install", 2, b"\x1b[B", "web-portal")):
            self.wait_for(lambda: (self.root / f"{step}.started").exists())
            rule = "━" * (30 * done) + "─" * (90 - 30 * done)
            screen.when("━" * (30 * done) if done else "agentkit · updating")
            self.assertIn(rule, ANSI.sub("", screen.text()))
            self.assertIn("agentkit · updating", screen.text())
            screen.key(key, f"<draw old {seat}>")
            self.release(step)
        screen.when("<draw new web-portal>")
        text = ANSI.sub("", screen.text())
        self.assertLess(text.index("━" * 90), text.index("<start new>"))
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.new, 1))
        for name in ("bridge", "boot", "maintenance"):
            self.assertEqual(set(re.findall(fr"<{name} (\d+)>", text)), {str(screen.proc.pid)})
        pid, group = re.search(r"<updater (\d+) (\d+)>", text).groups()
        self.assertEqual(pid, group)
        self.assertNotEqual(int(pid), screen.proc.pid)
        screen.leave()

    def test_a_typed_name_survives_until_esc_returns_to_the_main_screen(self):
        self.release("ls-remote", "fetch", "merge")
        screen = self.opened()
        self.wait_for(lambda: (self.root / "install.started").exists())
        screen.key(b"\x1b[B", "<draw old tidy-docs>")
        os.write(screen.master, b"n")
        screen.when("Name:")
        os.write(screen.master, b"acme-draft")
        screen.when("Name: acme-draft")
        self.release("install")
        self.wait_for(lambda: self.updaters() and not running(self.updaters()[0]))
        os.write(screen.master, b"-kept")
        screen.when("Name: acme-draft-kept")
        self.assertNotIn("<start new>", screen.text())
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), self.new)
        os.write(screen.master, b"\x1b")
        screen.when("<draw new tidy-docs>")
        self.assertEqual(self.installs(), 1)
        screen.leave()

    def test_esc_leaves_at_once_and_the_detached_install_finishes_once(self):
        self.release("ls-remote")
        screen = self.opened()
        screen.when("agentkit · updating")
        self.wait_for(lambda: (self.root / "fetch.started").exists())
        screen.leave()
        self.assertTrue(running(self.updaters()[0]))
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.first, 0))
        self.release("fetch", "merge", "install")
        self.wait_for(lambda: not running(self.updaters()[0]))
        self.assertTrue((self.root / "install.finished").exists())
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.new, 1))

    def test_an_update_that_fails_after_esc_is_retried_by_the_next_ak(self):
        self.release("ls-remote")
        failed = self.root / "fetch.fail"
        failed.touch()
        screen = self.opened()
        screen.when("agentkit · updating")
        screen.leave()
        self.release("fetch")
        self.wait_for(lambda: not running(self.updaters()[0]))
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.first, 0))
        failed.unlink()
        self.release("merge", "install")
        again = self.opened()
        again.when("<draw new fix-api>")
        self.assertEqual(self.installs(), 1)
        again.leave()

    def test_a_failed_fetch_is_a_notice_and_the_next_ak_tries_again(self):
        self.release("ls-remote", "fetch")
        failed = self.root / "fetch.fail"
        failed.touch()
        screen = self.opened()
        screen.when("fixture fetch failed")
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), self.first)
        os.write(screen.master, b"\r")
        screen.when("<draw old fix-api>", after=screen.text().encode().index(b"fixture fetch failed"))
        screen.leave()
        failed.unlink()
        self.release("merge", "install")
        again = self.opened()
        again.when("<draw new fix-api>")
        self.assertEqual(self.installs(), 1)
        again.leave()

    def test_an_unanswered_origin_never_delays_the_first_frame_or_esc(self):
        screen = self.opened()
        self.wait_for(lambda: (self.root / "ls-remote.started").exists())
        screen.key(b"\x1b[B", "<draw old tidy-docs>")
        screen.leave()
        self.assertTrue(running(self.updaters()[0]))
        (self.root / "ls-remote.fail").touch()
        self.release("ls-remote")
        self.wait_for(lambda: not running(self.updaters()[0]))
        self.assertNotIn("updating", screen.text())
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.first, 0))

    def test_a_killed_updater_clears_progress_after_its_notice(self):
        self.release("ls-remote")
        screen = self.opened()
        screen.when("agentkit · updating")
        self.wait_for(lambda: (self.root / "fetch.started").exists())
        os.killpg(self.updaters()[0], signal.SIGKILL)    # this test's detached updater only
        screen.when("agentkit update exited -9")
        after = len(screen.text().encode())
        os.write(screen.master, b"\r")
        screen.when("<draw old fix-api>", after)
        screen.key(b"\x1b[B", "<draw old tidy-docs>")
        self.assertNotIn("agentkit · updating", screen.text().encode()[after:].decode())
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.first, 0))
        screen.leave()

    def test_a_dirty_checkout_is_left_as_it_is(self):
        edited = self.clone / "notes"
        edited.write_text("somebody's edit\n")
        screen = self.opened()
        self.wait_for(lambda: self.updaters() and not running(self.updaters()[0]))
        self.assertNotIn("updating", screen.text())
        self.assertEqual((self.git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.first, 0))
        self.assertEqual(edited.read_text(), "somebody's edit\n")
        screen.leave()

    def test_overlay_and_dry_run_skip_the_update(self):
        for flag in ("--overlay", "--dry-run"):
            with self.subTest(flag=flag):
                screen = self.opened(flag)
                screen.leave()
                self.assertEqual(self.updaters(), [])
        self.assertEqual(self.installs(), 0)

    def test_a_client_connects_at_once_and_its_next_ak_opens_on_the_new_code(self):
        self.env["START_CLIENT"] = "1"
        (self.root / "ssh.hold").touch()
        screen = Screen(self)
        screen.when("<connected>")
        self.wait_for(lambda: (self.root / "ls-remote.started").exists())
        self.release("ssh")
        self.assertEqual(screen.proc.wait(10), 0, screen.text())
        self.assertTrue(running(self.updaters()[0]))
        self.release("ls-remote", "fetch", "merge", "install")
        self.wait_for(lambda: not running(self.updaters()[0]))
        self.assertEqual(self.installs(), 1)
        del self.env["START_CLIENT"]
        again = Screen(self)
        again.when("<draw new fix-api>")
        self.assertNotIn("<start old>", again.text())
        again.leave()


class UpdaterCleanup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-updater-cleanup-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.case = StartUpdate()
        self.case.root = Path(tmp.name)
        (self.case.root / "updaters").write_text("12345\n")

    def test_a_zombie_reaped_between_signal_and_stat_is_gone(self):
        stat = Mock()
        stat.exists.return_value = True
        stat.read_text.return_value = "12345 (updater) Z"

        def reap(pid, sig):
            if kill.call_count == 2:
                stat.exists.return_value = False
                stat.read_text.side_effect = FileNotFoundError

        with patch(__name__ + ".Path", return_value=stat), \
                patch.object(sys, "platform", "linux"), \
                patch.object(os, "kill", side_effect=reap) as kill, \
                patch.object(os, "killpg", side_effect=ProcessLookupError) as killpg:
            self.case.finish_updates()
        self.assertEqual(kill.call_count, 2)
        killpg.assert_not_called()

    def test_a_group_reaped_between_check_and_kill_is_gone(self):
        with patch(__name__ + ".running", return_value=True), \
                patch.object(time, "monotonic", side_effect=[0, 5]), \
                patch.object(os, "killpg", side_effect=ProcessLookupError) as killpg:
            self.case.finish_updates()
        killpg.assert_called_once_with(12345, signal.SIGKILL)


class OriginTimeout(unittest.TestCase):
    def test_an_unanswered_origin_is_bounded_and_its_group_is_killed(self):
        proc = Mock(pid=12345)
        proc.communicate.side_effect = subprocess.TimeoutExpired("git", update.START_WAIT)
        context = Mock()
        context.__enter__ = Mock(return_value=proc)
        context.__exit__ = Mock(return_value=False)
        with patch.object(update.subprocess, "Popen", return_value=context), \
                patch.object(update.os, "killpg") as kill:
            self.assertFalse(update.behind())
        proc.communicate.assert_called_once_with(timeout=update.START_WAIT)
        kill.assert_called_once_with(proc.pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
