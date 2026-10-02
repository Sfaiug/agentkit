"""A turn cannot read GitHub credentials or leave even an unmarked, detached child."""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import box, config, run, worker


ADAPTER = r'''import json, os, signal, subprocess, sys, time
from pathlib import Path
if sys.argv[1] == "auth":
    print("fixture login")
    sys.exit(0)
root = Path(os.environ["BOX_FIXTURE"])
out = Path(sys.argv[6])
if os.environ.get("BOX_TERM"):
    def term(*_):
        (out / "session_id").write_text("fixture-session")
        if os.environ["BOX_TERM"] == "exit":
            sys.exit(0)
    signal.signal(signal.SIGTERM, term)
def read(path):
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""
seen = {"hosts": read(Path.home() / ".config/gh/hosts.yml"),
        "token": os.environ.get("GH_TOKEN"),
        "store": read(Path.home() / ".git-credentials")}
if os.environ.get("BOX_PATHS"):
    seen["paths"] = [read(Path(path)) for path in json.loads(os.environ["BOX_PATHS"])]
    seen["tokens"] = [os.environ.get(key) for key in (
        "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")]
    seen["pid1_token"] = b"GH_TOKEN=" in Path("/proc/1/environ").read_bytes()
if os.environ.get("BOX_INSPECT"):
    (Path.home() / ".codex").mkdir(exist_ok=True)
    (Path.home() / ".codex/fixture").write_text("harness write")
    seen["home"] = str(Path.home())
    seen["cwd"] = os.getcwd()
    seen["uid"] = os.getuid()
    seen["provider"] = os.environ["FIXTURE_PROVIDER_TOKEN"]
if os.environ.get("BOX_NEST") == "1":
    os.environ["BOX_NEST"] = "0"
    sys.path.insert(0, os.environ["BOX_REPO"])
    from agentkit import config, worker
    config.adapter = lambda _harness: Path(sys.argv[0])
    cfg = json.loads((root / "cfg.json").read_text())
    logs = []
    code, text, _, killed, left = worker.turn(
        cfg, "w", "nested task", root, root / "nested", limit=10, log=logs.append)
    seen["nested"] = {"code": code, "seen": json.loads(text), "killed": killed,
                      "left": left, "logs": logs}
if os.environ.get("BOX_LEAK", "1") == "1":
    subprocess.Popen([sys.executable, str(root / "detached.py"), str(out)],
                     env={}, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 5
    while not (out / "ready").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("fixture child never started")
        time.sleep(.01)
(out / "final.md").write_text(json.dumps(seen))
(out / "events.jsonl").write_text("{}\n")
if os.environ.get("BOX_SIGNAL"):
    os.kill(os.getpid(), int(os.environ["BOX_SIGNAL"]))
if os.environ.get("BOX_HANG"):
    time.sleep(300)
sys.exit(int(os.environ.get("BOX_EXIT", "0")))
'''

DETACHED = r'''import fcntl, os, sys, time
from pathlib import Path
out = Path(sys.argv[1])
with (out / "alive.lock").open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    (out / "ready").write_text("ready")
    deadline = time.monotonic() + 30
    while not (out / "stop").exists() and time.monotonic() < deadline:
        time.sleep(.01)
'''


class WorkerBox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-worker-box-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "out"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "BOX_FIXTURE": str(self.root), "GH_TOKEN": "fixture-token",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "GH_CONFIG_DIR",
                    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "BOX_LEAK", "BOX_NEST", "BOX_HANG",
                    "BOX_EXIT", "BOX_INSPECT", "BOX_PATHS", "BOX_SIGNAL", "BOX_TERM"):
            os.environ.pop(key, None)
        self.stack.enter_context(patch.object(config, "RUNS", self.root / "runs"))
        # The only real child is our fixture. No marker sweep may inspect the hosting run.
        self.stack.enter_context(patch.object(worker, "marked_pids", return_value=[]))
        gh = self.root / ".config/gh"
        gh.mkdir(parents=True)
        (gh / "hosts.yml").write_text("fixture-login")
        (self.root / ".git-credentials").write_text("fixture-store")
        adapter = self.root / "adapter.py"
        adapter.write_text(f"#!{sys.executable}\n{ADAPTER}")
        adapter.chmod(0o755)
        (self.root / "detached.py").write_text(DETACHED)
        self.stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        self.cfg = {"models": {"w": {"harness": "fixture", "model": "fixture", "effort": "low",
                                    "provider": "fixture"}}, "providers": {"fixture": {}}}
        (self.root / "cfg.json").write_text(json.dumps(self.cfg))
        self.logs = []
        self.addCleanup(self.stop_child)

    def alive(self, out=None):
        with ((out or self.out) / "alive.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def stop_child(self):
        for lock in self.root.rglob("alive.lock"):
            out = lock.parent
            (out / "stop").touch()
            deadline = time.monotonic() + 5
            while self.alive(out) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(self.alive(out), "fixture child did not stop")

    def turn(self, limit=10):
        return worker.turn(self.cfg, "w", "fixture task", self.root, self.out,
                           limit=limit, log=self.logs.append)

    def test_credentials_and_unmarked_detached_child(self):
        code, text, _, killed, left = self.turn()
        self.assertEqual((code, killed), (0, False))
        self.assertEqual({**json.loads(text), "alive": self.alive(), "left": left,
                          "reported": any("detached.py" in line for line in self.logs)},
                         {"hosts": "", "token": None, "store": "", "alive": False,
                          "left": True, "reported": True})
        self.assertEqual((self.root / ".config/gh/hosts.yml").read_text(), "fixture-login")
        self.assertEqual((self.root / ".git-credentials").read_text(), "fixture-store")

    def test_paths_symlinks_and_all_token_variables(self):
        login, store = self.root / "login", self.root / "store"
        login.write_text("fixture-login")
        store.write_text("fixture-store")
        hosts = self.root / ".config/gh/hosts.yml"
        hosts.unlink()
        hosts.symlink_to(login)
        default = self.root / ".git-credentials"
        default.unlink()
        default.symlink_to(store)
        xdg, gh = self.root / "xdg", self.root / "gh"
        literal = self.root / "literal-$HOME"
        for path in (xdg / "gh/hosts.yml", xdg / "git/credentials", gh / "hosts.yml",
                     self.root / "named-store", self.root / "env-store", literal):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture-secret")
        (self.root / ".gitconfig").write_text(
            '[credential]\n\thelper = store --file "~/named-store"\n'
            '\thelper = store --file "$HOME/env-store"\n'
            f"\thelper = store --file '{literal}'\n")
        paths = [login, store, xdg / "gh/hosts.yml", xdg / "git/credentials", gh / "hosts.yml",
                 self.root / "named-store", self.root / "env-store", literal,
                 Path("/proc/1/root") / str(hosts).lstrip("/")]
        with patch.dict(os.environ, {
                "XDG_CONFIG_HOME": str(xdg), "GH_CONFIG_DIR": str(gh),
                "BOX_PATHS": json.dumps([str(path) for path in paths]),
                "GITHUB_TOKEN": "fixture-github", "GH_ENTERPRISE_TOKEN": "fixture-enterprise",
                "GITHUB_ENTERPRISE_TOKEN": "fixture-github-enterprise"}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        seen = json.loads(text)
        self.assertEqual(seen["paths"], [""] * len(paths))
        self.assertEqual(seen["tokens"], [None] * 4)
        self.assertFalse(seen["pid1_token"])
        self.assertEqual(login.read_text(), "fixture-login")
        self.assertEqual(store.read_text(), "fixture-store")

    def test_files_writes_identity_environment_and_exit_status_stay_the_same(self):
        with patch.dict(os.environ, {"BOX_LEAK": "0", "BOX_INSPECT": "1", "BOX_EXIT": "7",
                                     "FIXTURE_PROVIDER_TOKEN": "fixture-provider"}):
            code, text, _, killed, left = self.turn()
        self.assertEqual((code, killed, left), (7, False, False))
        seen = json.loads(text)
        self.assertEqual((seen["home"], seen["cwd"], seen["uid"], seen["provider"]),
                         (str(self.root), os.getcwd(), os.getuid(), "fixture-provider"))
        self.assertEqual((self.root / ".codex/fixture").read_text(), "harness write")

    def test_turns_can_run_inside_a_turn(self):
        with patch.dict(os.environ, {"BOX_NEST": "1", "BOX_REPO": str(REPO)}):
            code, text, _, killed, left = self.turn()
        nested = json.loads(text)["nested"]
        self.assertEqual((code, killed, left), (0, False, True))
        self.assertEqual((nested["code"], nested["killed"], nested["left"]), (0, False, True))
        self.assertEqual(nested["seen"], {"hosts": "", "token": None, "store": ""})
        self.assertTrue(any("detached.py" in line for line in nested["logs"]))
        self.assertFalse(self.alive(self.root / "nested"))
        self.assertFalse(self.alive())

    def test_signal_deaths_keep_their_status_without_reinterpreting_exit_codes(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=sig), patch.dict(os.environ, {
                    "BOX_LEAK": "0", "BOX_SIGNAL": str(sig)}):
                code, _, _, killed, left = self.turn()
                self.assertEqual((code, killed, left), (-sig, False, False))
                self.assertEqual(run.killed_word(code), f"killed ({sig.name})")
        for status in (137, 143):
            with self.subTest(exit=status), patch.dict(os.environ, {
                    "BOX_LEAK": "0", "BOX_EXIT": str(status)}):
                code, _, _, killed, left = self.turn()
                self.assertEqual((code, killed, left), (status, False, False))
                self.assertIsNone(run.killed_word(code))

    def test_silence_kills_unmarked_detached_children_too(self):
        with patch.dict(os.environ, {"BOX_HANG": "1", "BOX_TERM": "exit"}):
            code, _, session, killed, _ = self.turn(limit=2)
        self.assertEqual((code, session, killed), (worker.TIMEOUT, "fixture-session", True))
        self.assertTrue((self.out / "ready").exists())
        self.assertFalse(self.alive())

    def test_abort_and_interrupt_allow_harness_cleanup(self):
        with patch.dict(os.environ, {"BOX_HANG": "1", "BOX_TERM": "exit", "BOX_LEAK": "0"}):
            with self.subTest(stop="abort"), patch.object(worker, "auth_scanner", return_value=(
                    lambda out: "fixture login expired" if (out / "events.jsonl").exists() else None)):
                with self.assertRaises(worker.LoginExpired) as expired:
                    self.turn()
                self.assertEqual(expired.exception.session, "fixture-session")

            self.out = self.root / "interrupt"
            original = worker.subprocess.Popen.communicate
            interrupted = False

            def interrupt(proc, *args, **kwargs):
                nonlocal interrupted
                if proc.args[0] == "bwrap" and not interrupted:
                    deadline = time.monotonic() + 5
                    while not (self.out / "events.jsonl").exists():
                        if time.monotonic() > deadline:
                            raise RuntimeError("fixture adapter never started")
                        time.sleep(.01)
                    interrupted = True
                    raise KeyboardInterrupt
                return original(proc, *args, **kwargs)

            with self.subTest(stop="interrupt"), \
                    patch.object(worker.subprocess.Popen, "communicate", interrupt), \
                    self.assertRaises(KeyboardInterrupt):
                self.turn()
            self.assertEqual((self.out / "session_id").read_text(), "fixture-session")

    def test_term_resistant_turn_is_still_forcibly_destroyed(self):
        with patch.dict(os.environ, {"BOX_HANG": "1", "BOX_TERM": "ignore"}), \
                patch.object(worker, "KILL_GRACE", .2):
            code, _, session, killed, _ = self.turn(limit=2)
        self.assertEqual((code, session, killed), (worker.TIMEOUT, "fixture-session", True))
        self.assertFalse(self.alive())

    def test_launch_refuses_before_allocating_without_bubblewrap(self):
        with patch.object(box.shutil, "which", return_value=None), \
                patch.object(config, "ensure_dirs", side_effect=AssertionError("allocated run")), \
                self.assertRaisesRegex(config.Error, "sudo apt-get install -y bubblewrap"):
            run.main([str(self.root / "task.md")])

    def test_namespace_refusal_names_the_fix(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        bwrap = fake_bin / "bwrap"
        bwrap.write_text("#!/bin/sh\necho 'fixture: namespaces denied' >&2\nexit 1\n")
        bwrap.chmod(0o755)
        original = Path.read_text

        def read(path, **kwargs):
            if str(path) == "/proc/sys/kernel/unprivileged_userns_clone":
                return "0"
            return original(path, **kwargs)

        with patch.dict(os.environ, {"PATH": f"{fake_bin}:{os.environ['PATH']}"}), \
                patch.object(Path, "read_text", read), \
                patch.object(config, "ensure_dirs", side_effect=AssertionError("allocated run")), \
                self.assertRaisesRegex(config.Error, "sudo sysctl -w kernel.unprivileged_userns_clone=1"):
            run.main([str(self.root / "task.md")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
