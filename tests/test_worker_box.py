"""A turn cannot read GitHub credentials or leave even an unmarked, detached child."""

from contextlib import ExitStack
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import subprocess
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
if os.environ.get("BOX_AGENT"):
    import socket
    agent = socket.socket(socket.AF_UNIX)
    try:
        agent.connect(os.environ["BOX_AGENT"])
        seen["agent"] = True
    except OSError:
        seen["agent"] = False
    seen["agent_address"] = os.environ.get("SSH_AUTH_SOCK")
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
                    "BOX_EXIT", "BOX_INSPECT", "BOX_PATHS", "BOX_SIGNAL", "BOX_TERM", "BOX_AGENT",
                    "SSH_AUTH_SOCK"):
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

    def test_ssh_keys_and_agent_are_out_of_reach(self):
        key = self.root / ".ssh/id_fixture"
        key.parent.mkdir()
        key.write_text("fixture-key")
        # AF_UNIX paths are short; the checkout path may not be.
        short = tempfile.TemporaryDirectory(prefix="ak-agent-")
        self.addCleanup(short.cleanup)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        sock = Path(short.name) / "agent"
        listener.bind(str(sock))
        listener.listen(1)
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": str(sock), "BOX_AGENT": str(sock),
                                     "BOX_PATHS": json.dumps([str(key)])}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        seen = json.loads(text)
        self.assertEqual((seen["paths"], seen["agent"], seen["agent_address"]), ([""], False, None))
        self.assertEqual(key.read_text(), "fixture-key")

    def test_a_relative_agent_address_never_reaches_the_turn(self):
        # A relative address is the caller's: it names this socket in the caller's directory.
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        name = f".ak-test-agent-{os.getpid()}"
        listener.bind(name)
        self.addCleanup(os.unlink, name)
        listener.listen(1)
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": name, "BOX_AGENT": name}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        seen = json.loads(text)
        self.assertEqual((seen["agent"], seen["agent_address"]), (False, None))

    def test_an_agent_socket_inside_a_hidden_directory_still_starts(self):
        for place in (".ssh/agent", ".git-credential-cache/agent", ".cache/git/credential/agent"):
            with self.subTest(place=place):
                sock = self.root / place
                sock.parent.mkdir(parents=True, exist_ok=True)
                sock.write_text("")
                with patch.dict(os.environ, {"SSH_AUTH_SOCK": str(sock)}):
                    code, _, _, killed, _ = self.turn()
                self.assertEqual((code, killed), (0, False), self.logs)
                self.stop_child()

    def test_unusable_ssh_paths_still_start(self):
        ssh = self.root / ".ssh"
        cases = {"a link to itself": lambda: (ssh.mkdir(), (ssh / "self").symlink_to("self")),
                 "two links to each other": lambda: (
                     ssh.mkdir(), (ssh / "a").symlink_to("b"), (ssh / "b").symlink_to("a")),
                 "a looping .ssh": lambda: ssh.symlink_to(".ssh"),
                 "a file named .ssh": lambda: ssh.write_text("fixture")}
        for name, make in cases.items():
            with self.subTest(case=name):
                make()
                code, _, _, killed, _ = self.turn()
                self.assertEqual((code, killed), (0, False), self.logs)
                self.stop_child()
                if ssh.is_symlink() or ssh.is_file():
                    ssh.unlink()
                else:
                    shutil.rmtree(ssh)

    def test_keys_linked_into_ssh_stay_out_of_reach(self):
        vault, keys = self.root / "vault", self.root / "keydir"
        vault.mkdir()
        keys.mkdir()
        (vault / "id_linked").write_text("fixture-key")
        (keys / "id_dir").write_text("fixture-key")
        # Links inside a linked directory, and a loop that must not trap the walk.
        outside = self.root / "outside"
        (outside / "keydir").mkdir(parents=True)
        (outside / "id_file").write_text("fixture-key")
        (outside / "keydir/id_dir").write_text("fixture-key")
        (keys / "id_file").symlink_to(outside / "id_file")
        (keys / "keydir").symlink_to(outside / "keydir")
        (keys / "loop").symlink_to(keys)
        ssh = self.root / ".ssh"
        ssh.mkdir()
        (ssh / "id_linked").symlink_to("../vault/id_linked")
        (ssh / "keys").symlink_to(keys)
        paths = [vault / "id_linked", keys / "id_dir", outside / "id_file", outside / "keydir/id_dir"]
        with patch.dict(os.environ, {"BOX_PATHS": json.dumps([str(path) for path in paths])}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        self.assertEqual(json.loads(text)["paths"], [""] * len(paths))
        self.assertEqual([path.read_text() for path in paths], ["fixture-key"] * len(paths))

    def test_a_relative_home_hides_the_keys_where_the_turn_reads_them(self):
        # The turn resolves HOME=home in its own directory, not in the launcher's.
        key = self.root / "home/.ssh/id_fixture"
        key.parent.mkdir(parents=True)
        key.write_text("fixture-key")
        read = ("from pathlib import Path; key = Path.home() / '.ssh/id_fixture'; "
                "print(key.read_text() if key.exists() else '')")
        for walls in (True, False):
            with self.subTest(walls=walls), patch.dict(os.environ, {"HOME": "home"}):
                with box.command([sys.executable, "-c", read], dict(os.environ), cwd=self.root,
                                 walls=walls) as (cmd, env, _):
                    result = subprocess.run(cmd, env=env, cwd=self.root, capture_output=True,
                                            text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout.strip()), (0, ""), result.stderr)
        self.assertEqual(key.read_text(), "fixture-key")

    def test_a_closed_directory_on_the_way_to_a_key_refuses_the_box(self):
        # The command could open a closed directory it owns, so what it holds counts as there.
        def listed_not_entered(case):
            (case / "home/.ssh").mkdir(parents=True)
            (case / "home/.ssh/id_linked").symlink_to(case / "id_outside")
            return {"HOME": str(case / "home")}, case / "home/.ssh", 0o111

        def linked_directory(case):
            (case / "home/.ssh").mkdir(parents=True)
            (case / "keydir").mkdir()
            (case / "keydir/id_linked").symlink_to(case / "id_outside")
            (case / "home/.ssh/keys").symlink_to(case / "keydir")
            return {"HOME": str(case / "home")}, case / "keydir", 0o111

        def linked_key(case):
            (case / "home/.ssh").mkdir(parents=True)
            (case / "vault").mkdir()
            (case / "vault/id_fixture").write_text("fixture-key")
            (case / "home/.ssh/id_fixture").symlink_to(case / "vault/id_fixture")
            return {"HOME": str(case / "home")}, case / "vault", 0

        def home(case):
            (case / "home/.ssh").mkdir(parents=True)
            return {"HOME": str(case / "home")}, case / "home", 0

        def agent(case):
            (case / "vault").mkdir()
            return {"SSH_AUTH_SOCK": str(case / "vault/agent")}, case / "vault", 0

        for make in (listed_not_entered, linked_directory, linked_key, home, agent):
            case = self.root / make.__name__
            case.mkdir()
            (case / "id_outside").write_text("fixture-key")
            env, closed, mode = make(case)
            closed.chmod(mode)
            self.addCleanup(closed.chmod, 0o700)
            for walls in (True, False):
                with self.subTest(case=make.__name__, walls=walls), patch.dict(os.environ, env), \
                        self.assertRaisesRegex(config.Error, f"{re.escape(str(closed))}.* is closed to "
                                               f"you.*chmod u\\+rx"):
                    with box.command(["true"], dict(os.environ), cwd=self.root, walls=walls):
                        pass

    def test_the_credential_query_sees_no_token(self):
        # A git first on PATH answers the box's question about credential stores.
        bindir, seen, git = self.root / "bin", self.root / "seen.json", shutil.which("git")
        bindir.mkdir()
        (bindir / "git").write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            f"open({str(seen)!r}, 'w').write(json.dumps([os.environ.get(k) for k in {box.TOKENS!r}]))\n"
            f"os.execv({git!r}, [{git!r}, *sys.argv[1:]])\n")
        (bindir / "git").chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                                     "GITHUB_TOKEN": "fixture-github", "SSH_AUTH_SOCK": "agent"}):
            with box.command(["true"], dict(os.environ), cwd=self.root):
                pass
        self.assertEqual(json.loads(seen.read_text()), [None] * len(box.TOKENS))

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

    def test_commands_that_cannot_start_keep_shell_exit_codes(self):
        program = self.root / "unavailable"
        for mode, expected in ((None, 127), (0o644, 126), (0o755, 126)):
            with self.subTest(mode=mode):
                if mode is not None:
                    program.write_text("invalid executable\n")
                    program.chmod(mode)
                with patch.object(config, "adapter", return_value=program):
                    code, _, _, killed, left = self.turn()
                self.assertEqual((code, killed, left), (expected, False, False))
                self.assertEqual(box.returncode(self.out, -1), expected)
                diagnostic = (self.out / "stderr.log").read_text()
                self.assertIn(str(program), diagnostic)
                self.assertNotIn("Traceback", diagnostic)

                activity = self.root / "check.log"
                with activity.open("w+b") as output:
                    code, _, killed = worker.boxed(
                        [str(program)], 10, env=dict(os.environ), cwd=self.root,
                        activity=activity, output=output, stderr=subprocess.STDOUT)
                    output.seek(0)
                    diagnostic = output.read().decode()
                self.assertEqual((code, killed), (expected, False))
                self.assertIn(str(program), diagnostic)
                self.assertNotIn("Traceback", diagnostic)

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

    def test_job_resume_refuses_before_starting_without_bubblewrap(self):
        receipt = self.root / "jobs" / "job-acme"
        receipt.mkdir(parents=True)
        run.jobs.save_job(receipt, {
            "job_id": "job-acme", "tasks": [{"name": "fix-api", "state": "queued"}]})
        with patch.dict(os.environ, {config.RUN_DIR_ENV: "", config.JOB_DIR_ENV: ""}), \
                patch.object(config, "JOBS", receipt.parent), \
                patch.object(config, "load", return_value={}), \
                patch.object(box.shutil, "which", return_value=None), \
                patch.object(run.jobs, "run_job_loop", return_value=0) as loop, \
                patch.object(run.jobs, "spawn_job_bg", return_value=0) as spawn:
            for tail in ([], ["--bg"]):
                with self.subTest(tail=tail), \
                        self.assertRaisesRegex(config.Error, "sudo apt-get install -y bubblewrap"):
                    run.cmd_resume([receipt.name, *tail])
            loop.assert_not_called()
            spawn.assert_not_called()

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

    def test_a_slow_probe_on_a_busy_host_is_no_refusal(self):
        # bubblewrap works here; under landing load its probe can outlast the wait.
        slow = box.subprocess.TimeoutExpired("bwrap", 10)
        with patch.object(box.subprocess, "run", side_effect=slow):
            self.assertIsNone(box.check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
