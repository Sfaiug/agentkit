"""Proofs and checks have the worker's credential masks and process teardown."""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, hand_in, run, worker


class ChecksBoxed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-checks-boxed-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GH_TOKEN": "fixture-token",
            "GH_CONFIG_DIR": str(self.root / ".config/gh"),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "STATE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(gate, "derived_heavy_limit", return_value=2))
        self.stack.enter_context(patch.object(gate._SuiteMeasure, "save"))
        self.credential = self.root / ".config/gh/hosts.yml"
        self.credential.parent.mkdir(parents=True)
        self.credential.write_text("fixture-login")
        self.lp = SimpleNamespace(scratch=True, wt=self.root, run_dir=self.root,
                                  done_when_limit=10, turn_limit=10, log=lambda _: None)

    def command(self, source):
        return shlex.join([sys.executable, "-u", "-c", source])

    def proof(self, command):
        return run.proof_on(self.lp, command, self.root / "proof.log")

    def check(self, command, **kwargs):
        return gate.run_done_when([command], self.root, self.root / "check.log", set(),
                                  limit=10, silence=5, **kwargs)

    def credentials_command(self):
        return self.command(
            "import json, os; from pathlib import Path; "
            "print(json.dumps({'file': Path(os.environ['GH_CONFIG_DIR'], 'hosts.yml').read_text(), "
            "'token': os.environ.get('GH_TOKEN')}))")

    def test_proof_cannot_read_credential_file_or_token(self):
        result = self.proof(self.credentials_command())
        self.assertEqual((result["returncode"], result["killed"]), (0, False), result)
        self.assertEqual(json.loads(result["output"]), {"file": "", "token": None})
        self.assertEqual(self.credential.read_text(), "fixture-login")

    def test_done_when_cannot_read_credential_file_or_token(self):
        for suffix in ("", " # AK_SHARD"):
            with self.subTest(command=suffix or "whole"):
                ok, text = self.check(self.credentials_command() + suffix)
                self.assertTrue(ok, text)
                seen = [json.loads(line) for line in text.splitlines() if line.startswith('{"file"')]
                self.assertTrue(seen, text)
                self.assertEqual(seen, [{"file": "", "token": None}] * len(seen))
                self.assertEqual(self.credential.read_text(), "fixture-login")

    def test_proof_and_check_cannot_read_ssh_keys(self):
        key = self.root / ".ssh/id_fixture"
        key.parent.mkdir()
        key.write_text("fixture-key")
        command = self.command(
            "import os; from pathlib import Path; p = Path(os.environ['HOME'], '.ssh/id_fixture'); "
            "print('key:' + (p.read_text() if p.exists() else ''))")
        result = self.proof(command)
        self.assertEqual((result["returncode"], result["output"].strip()), (0, "key:"), result)
        ok, text = self.check(command)
        self.assertTrue(ok, text)
        self.assertIn("key:\n", text + "\n")
        self.assertNotIn("fixture-key", text)
        self.assertEqual(key.read_text(), "fixture-key")

    def alive(self):
        with (self.root / "alive.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def test_manager_outside_the_box_is_unavailable(self):
        runtime = self.root / "runtime"
        (runtime / "systemd").mkdir(parents=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        # A relative name fits AF_UNIX even when the checkout path is long.
        listener.bind(str((runtime / "systemd/private").relative_to(REPO)))
        listener.listen(16)
        bindir = self.root / "bin"
        bindir.mkdir()
        binary = bindir / "systemd-run"
        binary.write_text("#!/bin/sh\nexit 97\n")
        binary.chmod(0o755)
        command = self.command(
            f"import sys; sys.path.insert(0, {str(REPO)!r}); "
            "from agentkit import orch; print(orch.user_manager())")
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "runtime",
                                     "PATH": f"{bindir}:{os.environ['PATH']}"}):
            for name in ("proof", "whole", "sharded"):
                with self.subTest(command=name):
                    if name == "proof":
                        result = self.proof(command)
                        self.assertEqual(result["returncode"], 0, result)
                        text = result["output"]
                    else:
                        ok, text = self.check(command + (" # AK_SHARD" if name == "sharded" else ""))
                        self.assertTrue(ok, text)
                    seen = [line for line in text.splitlines() if line in ("True", "False")]
                    self.assertTrue(seen, text)
                    self.assertEqual(seen, ["False"] * len(seen))

    def stop_sleeper(self):
        # The pre-fix failure also cleans up its own fixture, without inspecting host PIDs.
        (self.root / "stop").touch()
        deadline = time.monotonic() + 5
        while self.alive() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.alive(), "fixture sleep did not stop")

    def test_done_when_ends_unmarked_detached_background_sleep(self):
        sleeper = self.root / "sleeper.py"
        sleeper.write_text(
            "import fcntl, subprocess, sys, time\nfrom pathlib import Path\n"
            "root = Path(sys.argv[1])\n"
            "with (root / 'alive.lock').open('a') as lock:\n"
            " fcntl.flock(lock, fcntl.LOCK_EX)\n"
            " child = subprocess.Popen(['sleep', '600'], env={}, start_new_session=True, "
            "pass_fds=(lock.fileno(),))\n"
            " (root / 'ready').touch()\n"
            " while not (root / 'stop').exists():\n  time.sleep(.01)\n"
            " child.terminate()\n child.wait()\n")
        self.addCleanup(self.stop_sleeper)
        command = self.command(
            "import subprocess, sys, time; from pathlib import Path; "
            f"root = Path({str(self.root)!r}); "
            "subprocess.Popen([sys.executable, str(root / 'sleeper.py'), str(root)], "
            "env={}, start_new_session=True, stdin=subprocess.DEVNULL, "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
            "deadline = time.monotonic() + 5\n"
            "while not (root / 'ready').exists():\n"
            " if time.monotonic() > deadline: raise RuntimeError('fixture sleep never started')\n"
            " time.sleep(.01)")
        ok, text = self.check(command)
        self.assertTrue(ok, text)
        self.assertTrue((self.root / "ready").exists())
        self.assertFalse(self.alive(), "done-when left its background sleep running")

    def test_output_and_signal_status_are_preserved(self):
        for command, code in (("printf 'partial'; exit 7", 7),
                              ("printf 'partial'; kill -TERM $$", -15),
                              ("printf 'partial'; exit 143", 143)):
            with self.subTest(command=command):
                result = self.proof(command)
                self.assertEqual((result["returncode"], result["killed"], result["output"]),
                                 (code, False, "partial"))
                ok, text = self.check(command)
                self.assertFalse(ok, text)
                self.assertIn(f"[exit {code}]\npartial", text)

    def test_a_check_writes_where_its_project_says(self):
        # A suite may log to /tmp or fill a cache in HOME; only worker turns are walled.
        outside = tempfile.TemporaryDirectory(prefix="ak-test-checks-boxed-")
        self.addCleanup(outside.cleanup)
        for name in ("proof", "check"):
            with self.subTest(command=name):
                target = Path(outside.name) / name
                command = f"echo written > {shlex.quote(str(target))}"
                if name == "proof":
                    result = self.proof(command)
                    self.assertEqual(result["returncode"], 0, result)
                else:
                    ok, text = self.check(command)
                    self.assertTrue(ok, text)
                self.assertEqual(target.read_text(), "written\n")

    def test_a_box_that_cannot_start_proves_nothing(self):
        # bwrap exits 1 on a mount it cannot make, before its supervisor runs the command.
        bindir = self.root / "bin"
        bindir.mkdir()
        wrapper = bindir / "bwrap"
        missing = self.root / "missing-mount-source"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join(
            [shutil.which("bwrap"), "--ro-bind", str(missing), str(missing)]) + ' "$@"\n')
        wrapper.chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
            result = self.proof("touch started; exit 7")
            self.assertFalse((self.root / "started").exists())
            self.assertEqual((result["returncode"], result["killed"]), (126, False), result)
            self.assertFalse(hand_in.proof_failed(result), result)
            ok, text = self.check("true")
            self.assertFalse(ok, text)
            self.assertIn("[exit 126]", text)

    def test_orphans_are_reaped_while_the_output_drains(self):
        # The shell is gone at once; its background child holds the output and leaves
        # exited children to PID 1, which must not let them pile up until forks fail.
        source = (
            "import os, pathlib, time\n"
            "while os.getppid() != 1:\n    time.sleep(.01)\n"
            "for _ in range(20):\n"
            "    child = os.fork()\n"
            "    if child == 0:\n        os.fork()\n        os._exit(0)\n"
            "    os.waitpid(child, 0)\n"
            "time.sleep(1)\n"
            "states = []\n"
            "for entry in pathlib.Path('/proc').iterdir():\n"
            "    try:\n"
            "        states.append((entry / 'stat').read_text().rsplit(')', 1)[1].split()[0])\n"
            "    except (OSError, IndexError):\n        pass\n"
            "print('zombies', states.count('Z'))\n")
        for name in ("proof", "check"):
            with self.subTest(command=name):
                command = self.command(source) + " &"
                text = (self.proof(command)["output"] if name == "proof"
                        else self.check(command)[1])
                self.assertIn("zombies 0", text)

    def test_a_launcher_keeps_the_supervisor_it_loaded(self):
        # A probe may check out another revision of ak's own checkout under the launcher.
        copy = self.root / "copy"
        shutil.copytree(REPO / "agentkit", copy / "agentkit",
                        ignore=shutil.ignore_patterns("__pycache__"))
        driver = (
            "import sys\nfrom pathlib import Path\nfrom types import SimpleNamespace\n"
            "sys.path.insert(0, sys.argv[1])\nfrom agentkit import box, gate, run\n"
            "Path(box.__file__).write_text('raise SystemExit(99)\\n')\n"
            "root = Path(sys.argv[2])\n"
            "lp = SimpleNamespace(scratch=True, wt=root, run_dir=root, done_when_limit=10,\n"
            "                     turn_limit=10, log=lambda _: None)\n"
            "print(run.proof_on(lp, 'printf started; exit 7', root / 'proof.log'))\n"
            "print(gate.run_done_when(['printf started; exit 7'], root, root / 'check.log', set(),\n"
            "                         limit=10, silence=5)[1])\n")
        result = subprocess.run([sys.executable, "-c", driver, str(copy), str(self.root)],
                                capture_output=True, text=True, timeout=120)
        self.assertIn("{'returncode': 7, 'output': 'started', 'killed': False}", result.stdout,
                      result)
        self.assertIn("[exit 7]\nstarted", result.stdout, result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
