"""Only a turn's workspace, output and declared harness state keep its writes."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import box, config, worker


ADAPTER = r'''import fcntl, json, multiprocessing, os, pty, socket, subprocess, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
if sys.argv[1] == "auth":
    print("fixture login")
    sys.exit(0)
ws, out = Path(sys.argv[4]), Path(sys.argv[6])
mode = os.environ["WRITE_MODE"]
seen = {}
if mode == "reviewer":
    for name in json.loads(os.environ["WRITE_OUTSIDE"]):
        try:
            Path(name).write_text("reviewer write\n")
        except OSError:
            pass
    (ws / "copy.txt").write_text("reviewer copy\n")
elif mode == "executor":
    (ws / "built.txt").write_text("executor work\n")
    for args in (("add", "built.txt"), ("commit", "-qm", "executor work")):
        subprocess.run(["git", "-C", str(ws), *args], check=True)
elif mode == "state":
    state = Path(os.environ.get("ACME_STATE") or Path.home() / ".acme")
    state.mkdir(parents=True, exist_ok=True)
    sessions = state / "sessions"
    sessions.mkdir(exist_ok=True)
    login = state / "auth.json"
    with (state / "auth.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    if len(sys.argv) > 7:
        seen["login"] = login.read_text()
        seen["session"] = (sessions / sys.argv[7]).read_text()
    if login.is_symlink():
        login.write_text("in-place refresh")
    fresh = state / "auth.new"
    fresh.write_text("refreshed login")
    fresh.replace(login.resolve() if os.environ.get("LOGIN_RESOLVE") else login)
    (sessions / "fixture-session").write_text("saved conversation")
elif mode == "temporary":
    with tempfile.NamedTemporaryFile(delete=False) as scratch:
        scratch.write(b"disk scratch")
        seen["temporary"] = scratch.name
        seen["disk"] = os.fstat(scratch.fileno()).st_dev == out.stat().st_dev
elif mode == "socket":
    with multiprocessing.Manager() as manager:
        seen["manager"] = dict(manager.dict(a=1))
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(Path(directory) / "app.sock"))
            seen["socket"] = True
elif mode == "devices":
    multiprocessing.Lock()
    with multiprocessing.Pool(1) as pool:
        seen["pool"] = pool.apply(pow, (2, 3))
    with ProcessPoolExecutor(max_workers=1) as pool:
        seen["executor"] = pool.submit(pow, 2, 3).result()
    master, slave = pty.openpty()
    os.close(master)
    os.close(slave)
    with open("/dev/null", "wb") as device:
        device.write(b"device access")
    seen["devices"] = [path for path in json.loads(os.environ["DEVICES"]) if Path(path).exists()]
elif mode == "memory":
    for name, directory in (("shm", "/dev/shm"),
                            ("credentials", Path.home() / ".git-credential-cache")):
        try:
            with tempfile.TemporaryFile(dir=directory) as scratch:
                scratch.write(b"disk scratch")
                seen[name] = "writable"
                seen[name + "_disk"] = os.fstat(scratch.fileno()).st_dev == out.stat().st_dev
        except OSError:
            seen[name] = "refused"
(out / "final.md").write_text(json.dumps(seen))
(out / "events.jsonl").write_text("{}\n")
(out / "session_id").write_text("fixture-session")
'''


class TurnWritesStayHome(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-turn-writes-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home, self.repo, self.wt = (self.root / name for name in ("home", "acme", "worktree"))
        self.home.mkdir()
        self.repo.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("AGENTKIT_", "AK_")) and key not in (
                   "ACME_STATE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")}
        env.update(HOME=str(self.home), TMPDIR=str(self.root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        self.stack.enter_context(patch.object(config, "RUNS", self.root / "runs"))
        self.stack.enter_context(patch.object(worker, "marked_pids", return_value=[]))
        adapters = self.root / "adapters"
        adapters.mkdir()
        adapter = adapters / "acme.sh"
        adapter.write_text(f"#!{sys.executable}\n{ADAPTER}")
        adapter.chmod(0o755)
        (adapters / "acme.toml").write_text(
            'version = 1\n[worker]\nstate = ["~/.acme", "$ACME_STATE"]\n'
            'logins = ["~/.acme/auth.json", "$ACME_STATE/auth.json", "~/.acme/auth.lock"]\n')
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.cfg = {"models": {"w": {"harness": "acme", "model": "fixture", "effort": "low",
                                    "provider": "acme"}}, "providers": {"acme": {}}}
        self.git(self.repo, "init", "-qb", "main")
        self.git(self.repo, "config", "user.name", "Fixture")
        self.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "base")
        self.git(self.repo, "worktree", "add", "-qb", "ak/fix-api", str(self.wt))

    def git(self, path, *args):
        return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()

    def turn(self, workspace, mode, session=None, places=(), **env):
        out = self.root / "out" / ("second" if session else "first")
        result = worker.turn(self.cfg, "w", "fixture task", workspace, out,
                             role="reviewer" if mode == "reviewer" else "executor",
                             session=session, env={"WRITE_MODE": mode, **env}, limit=10,
                             places=places)
        self.assertEqual((result[0], result[3], result[4]), (0, False, False),
                         (out / "stderr.log").read_text() if (out / "stderr.log").exists() else result)
        return json.loads(result[1]), result[2], out

    def test_reviewer_writes_survive_only_in_its_copy(self):
        copy = self.root / "review-copy"
        shutil.copytree(self.wt, copy, ignore=shutil.ignore_patterns(".git"))
        self.git(copy, "init", "-qb", "review")
        outside = [self.wt / "reviewer.txt", self.home / "reviewer.txt",
                   self.repo / "reviewer.txt", self.root / "peer-worktree/reviewer.txt",
                   self.home / ".agentkit/runs/acme/reviewer.txt"]
        for path in outside:
            path.parent.mkdir(parents=True, exist_ok=True)
        (copy / "escape").symlink_to(self.wt, target_is_directory=True)
        self.turn(copy, "reviewer", WRITE_OUTSIDE=json.dumps(
            [str(path) for path in [*outside, copy / "escape/via-link.txt"]]))
        self.assertEqual((copy / "copy.txt").read_text(), "reviewer copy\n")
        self.assertEqual([str(path) for path in [*outside, self.wt / "via-link.txt"]
                          if path.exists()], [], "reviewer wrote outside its copy")

    def test_a_place_is_writable_whatever_its_name(self):
        # A place is a literal directory, not a manifest path to expand.
        place = self.root / "run-$acme/regression"
        place.mkdir(parents=True)
        self.turn(self.wt, "reviewer", places=[place],
                  WRITE_OUTSIDE=json.dumps([str(place / "regression.sh")]))
        self.assertEqual((place / "regression.sh").read_text(), "reviewer write\n")

    def test_executor_commit_lands_on_its_worktree_branch(self):
        base = self.git(self.repo, "rev-parse", "main")
        self.turn(self.wt, "executor")
        self.assertEqual(self.git(self.wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual(self.git(self.wt, "log", "-1", "--format=%s"), "executor work")
        self.assertEqual(self.git(self.wt, "status", "--porcelain"), "")
        self.assertEqual(self.git(self.repo, "show", "ak/fix-api:built.txt"), "executor work")
        self.assertEqual(self.git(self.repo, "rev-parse", "main"), base)

    def test_manifest_state_keeps_refreshed_login_and_resumes_next_turn(self):
        for state in (self.home / ".acme", self.root / "custom-state"):
            with self.subTest(state=state):
                env = {} if state == self.home / ".acme" else {"ACME_STATE": str(state)}
                _, session, _ = self.turn(self.wt, "state", **env)
                seen, resumed, _ = self.turn(self.wt, "state", session=session, **env)
                self.assertEqual(seen, {"login": "refreshed login", "session": "saved conversation"})
                self.assertEqual(resumed, session)
                self.assertEqual((state / "auth.json").read_text(), "refreshed login")

    def test_temporary_files_use_disk_and_are_discarded_after_the_turn(self):
        seen, _, out = self.turn(self.wt, "temporary")
        self.assertTrue(seen["disk"])
        self.assertFalse(Path(seen["temporary"]).exists())
        self.assertFalse(any(path.name.startswith("tmp") for path in out.rglob("*")))

    def test_long_output_paths_still_allow_unix_sockets(self):
        self.root = self.root / ".agentkit/runs" / ("acme-" * 12) / "round-1/executor"
        seen, _, _ = self.turn(self.wt, "socket", TMPDIR="/tmp")
        self.assertEqual(seen, {"manager": {"a": 1}, "socket": True})

    def test_shared_memory_and_host_devices_still_work(self):
        # A turn really holds each of these that the box binds; tests/test_worker_box.py
        # proves which nodes those are.
        devices = [str(device) for device in box._devices()
                   if str(device).startswith(("/dev/fuse", "/dev/kvm", "/dev/net/tun", "/dev/dri/"))]
        seen, _, _ = self.turn(self.wt, "devices", DEVICES=json.dumps(devices))
        self.assertEqual(seen, {"pool": 8, "executor": 8, "devices": devices})

    def test_linked_login_keeps_in_place_and_atomic_refreshes(self):
        state = self.home / ".acme"
        state.mkdir()
        login = self.root / "borrowed-login"
        login.write_text("old login")
        (state / "auth.json").symlink_to(login)
        lock = self.root / "borrowed-lock"
        lock.touch()
        (state / "auth.lock").symlink_to(lock)
        _, session, _ = self.turn(self.wt, "state")
        self.assertEqual(login.read_text(), "in-place refresh")
        self.assertEqual((state / "auth.json").read_text(), "refreshed login")
        seen, _, _ = self.turn(self.wt, "state", session=session)
        self.assertEqual(seen, {"login": "refreshed login", "session": "saved conversation"})

    def test_linked_login_lock_can_be_created_on_its_first_refresh(self):
        state = self.home / ".acme"
        state.mkdir()
        lock = self.root / "borrowed-lock"
        (state / "auth.lock").symlink_to(lock)
        self.assertFalse(lock.exists())
        self.turn(self.wt, "state")
        self.assertTrue(lock.is_file())
        self.assertEqual((state / "auth.lock").stat().st_ino, lock.stat().st_ino)

    def test_linked_login_can_atomically_refresh_its_target_in_its_own_state(self):
        state = self.home / ".acme"
        state.mkdir()
        target = state / "token.json"
        target.write_text("old login")
        (state / "auth.json").symlink_to(target)
        _, session, _ = self.turn(self.wt, "state", LOGIN_RESOLVE="1")
        seen, _, _ = self.turn(self.wt, "state", session=session, LOGIN_RESOLVE="1")
        self.assertEqual(seen, {"login": "refreshed login", "session": "saved conversation"})
        self.assertEqual(target.read_text(), "refreshed login")

    def test_shared_memory_uses_disk(self):
        (self.home / ".git-credential-cache").mkdir()
        seen, _, out = self.turn(self.wt, "memory")
        self.assertEqual(seen["credentials"], "refused")
        self.assertEqual(seen["shm"], "writable")
        self.assertTrue(seen["shm_disk"])
        self.assertFalse(any(path.name.startswith("tmp") for path in out.rglob("*")))

    def test_muse_refusal_records_only_its_accounts_quota_outside_the_box(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        cli = binaries / "muse"
        cli.write_text('#!/bin/sh\necho "HTTP 429 subscription quota exhausted; '
                       'resets at 2099-01-02T03:04:05Z" >&2\nexit 1\n')
        cli.chmod(0o755)
        self.cfg["models"]["w"].update(harness="muse", provider="meta")
        self.cfg["providers"] = {"meta": {}}
        state = self.home / ".agentkit/state"
        state.mkdir(parents=True)
        (state / "unrelated.json").write_text("unchanged")
        with patch.object(config, "STATE", state), \
                patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(REPO / "adapters"),
                                        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}"}), \
                patch.object(worker, "auth_ok", return_value=(True, "")):
            for account in ("", "second"):
                with self.subTest(account=account):
                    out = self.root / "quota" / (account or "default")
                    result = worker.turn(self.cfg, "w", "fixture task", self.wt, out, limit=10,
                                         env={"AGENTKIT_ACCOUNT": account})
                    self.assertEqual(result[0], 1)
                    record = state / f"usage-meta{'.' + account if account else ''}.json"
                    self.assertTrue(record.exists(), (out / "stderr.log").read_text())
                    self.assertEqual(json.loads(record.read_text())["meters"][0]["used"], 100)
                    reading = subprocess.run([str(REPO / "adapters/muse.sh"), "usage"],
                                             env={**os.environ, "AGENTKIT_ACCOUNT": account},
                                             text=True, capture_output=True, timeout=10)
                    self.assertEqual(json.loads(reading.stdout)["meters"][0]["used"], 100)
        self.assertEqual((state / "unrelated.json").read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main(verbosity=2)
