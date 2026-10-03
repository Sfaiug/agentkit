"""Proofs and checks have the worker's credential masks and process teardown."""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, run, worker


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

    def alive(self):
        with (self.root / "alive.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
