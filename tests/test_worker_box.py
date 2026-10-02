"""A turn cannot read GitHub credentials or leave even an unmarked, detached child."""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, worker


ADAPTER = r'''import json, os, subprocess, sys, time
from pathlib import Path
if sys.argv[1] == "auth":
    print("fixture login")
    sys.exit(0)
root = Path(os.environ["BOX_FIXTURE"])
out = Path(sys.argv[6])
def read(path):
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""
seen = {"hosts": read(Path.home() / ".config/gh/hosts.yml"),
        "token": os.environ.get("GH_TOKEN"),
        "store": read(Path.home() / ".git-credentials")}
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
                    "XDG_CONFIG_HOME"):
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
        self.logs = []
        self.addCleanup(self.stop_child)

    def alive(self):
        with (self.out / "alive.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def stop_child(self):
        if self.out.exists():
            (self.out / "stop").touch()
            deadline = time.monotonic() + 5
            while self.alive() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(self.alive(), "fixture child did not stop")

    def test_credentials_and_unmarked_detached_child(self):
        code, text, _, killed, left = worker.turn(
            self.cfg, "w", "fixture task", self.root, self.out, limit=10, log=self.logs.append)
        self.assertEqual((code, killed), (0, False))
        self.assertEqual({**json.loads(text), "alive": self.alive(), "left": left,
                          "reported": any("detached.py" in line for line in self.logs)},
                         {"hosts": "", "token": None, "store": "", "alive": False,
                          "left": True, "reported": True})
        self.assertEqual((self.root / ".config/gh/hosts.yml").read_text(), "fixture-login")
        self.assertEqual((self.root / ".git-credentials").read_text(), "fixture-store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
