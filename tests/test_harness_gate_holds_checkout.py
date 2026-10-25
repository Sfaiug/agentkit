"""A harness upgrade's gates test one agentkit commit from start to end.

While an upgrade runs, no move of ~/agentkit -- the tick's go-live, `ak update`'s or `ak`'s
start -- fast-forwards it or runs its install.sh; the tick after the upgrade moves it, and only
then says it is live.  An upgrade that begins while a move is under way waits for that move to
end before it reads the checkout.

Offline throughout: origin is a throwaway bare repository one commit ahead of ~/agentkit, its
clone under a temporary HOME, whose install.sh is a fake that waits while `hold` sits beside the
clone; `acme` is a fake harness there, and its upgrade runs in-process.  The real ~/agentkit,
its origin and every real harness are never read or written here.
"""

from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, update

STEP = update.step      # the real one, which the gate below wraps
INSTALL = """#!/bin/sh
d="$(dirname "$0")/.."
echo began >>"$d/installs"
while [ -e "$d/hold" ]; do sleep 0.01; done
echo ended >>"$d/installs"
"""
MANIFEST = """version = 1
[update]
version = ["acme", "--version"]
upgrade = ["acme", "upgrade"]
revert = ["acme", "install", "{version}"]
"""
ACME = """#!/bin/sh
case "$1" in
  --version) cat "{root}/installed" ;;
  upgrade) echo 2.0.0 >"{root}/installed" ;;
  install) echo "$2" >"{root}/installed" ;;
esac
"""


def git(where, *args):
    return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


class HarnessGateHoldsCheckout(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-gate-holds-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name).resolve()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for directory in ("bin", "adapters"):
            (root / directory).mkdir()
        (root / "adapters/acme.toml").write_text(MANIFEST)
        (root / "bin/acme").write_text(ACME.format(root=root))
        (root / "bin/acme").chmod(0o755)
        (root / "installed").write_text("1.0.0\n")
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
            config.ADAPTER_DIR_ENV: str(root / "adapters"), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}))
        stack.enter_context(patch.object(config, "HOME", root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        stack.enter_context(patch.object(config, "load", return_value={
            "models": {"acme-model": {"harness": "acme", "provider": "acme"}},
            "providers": {"acme": {}}}))
        origin, seed, self.clone = root / "origin.git", root / "seed", root / "agentkit"
        stack.enter_context(patch.object(config, "REPO", self.clone))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                       check=True, timeout=60)
        subprocess.run(["git", "clone", "-q", str(origin), str(seed)],
                       check=True, capture_output=True, timeout=60)
        git(seed, "symbolic-ref", "HEAD", "refs/heads/main")
        (seed / "tests").mkdir()
        for name, text in (("install.sh", INSTALL), ("tests/live.sh", "exit 0\n")):
            (seed / name).write_text(text)
            (seed / name).chmod(0o755)
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "first")
        git(seed, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(origin), str(self.clone)],
                       check=True, capture_output=True, timeout=60)
        self.old = git(self.clone, "rev-parse", "HEAD")
        (seed / "notes").write_text("second\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "second")
        git(seed, "push", "-q", "origin", "main")
        self.new = git(seed, "rev-parse", "HEAD")
        # its tests/live.sh passed already, so only the upgrade holds its move
        check = config.STATE / update.LIVE / f"{self.new}-{int(time.time())}"
        check.mkdir(parents=True)
        (check / "exit").write_text("0\n")
        self.during = lambda: None    # what happens while the live gate runs
        self.gates = []               # each live gate: HEAD and installs at its start and end
        stack.enter_context(patch.object(update, "step", side_effect=self.gate))

    def gate(self, cmd, fh, env=None, timeout=update.STEP_CAP, **_kw):
        if not cmd[-1].endswith("live.sh"):
            return STEP(cmd, fh, env, timeout)
        began = (self.head(), self.installs())
        self.during()
        passed = STEP(cmd, fh, env, timeout)
        self.gates.append([began, (self.head(), self.installs())])
        return passed

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def installs(self):
        path = self.root / "installs"
        return path.read_text().split() if path.exists() else []

    def tick(self):
        """One tick's go-live: what it logged."""
        said = []
        update.go_live(said.append)
        return said

    def test_a_move_due_during_the_gate_goes_live_after_the_upgrade(self):
        during = []
        self.during = lambda: during.append((self.tick(), update.update_agentkit()))
        self.assertEqual(update.background("acme"), 0)
        self.assertEqual((self.root / "installed").read_text(), "2.0.0\n")
        self.assertEqual(during, [([], 0)])          # neither moved, and the tick said nothing
        self.assertEqual(self.gates, [[(self.old, []), (self.old, [])]])
        self.assertEqual(self.tick(), [f"agentkit is live at {self.new[:12]}"])
        self.assertEqual((self.head(), self.installs()), (self.new, ["began", "ended"]))
        self.assertEqual(self.tick(), [])

    def test_an_upgrade_begun_during_a_move_waits_for_it(self):
        (self.root / "hold").write_text("")
        with redirect_stdout(io.StringIO()):         # what the move says, as `ak` keeps it
            move = threading.Thread(target=update.update_agentkit)
            move.start()
            while not self.installs():               # fast-forwarded, install.sh running
                time.sleep(0.01)
            upgrade = threading.Thread(target=update.background, args=("acme",))
            upgrade.start()
            deadline = time.monotonic() + 2          # an upgrade that did not wait gates at once
            while not self.gates and time.monotonic() < deadline:
                time.sleep(0.01)
            (self.root / "hold").unlink()
            move.join()
            upgrade.join()
        done = (self.new, ["began", "ended"])
        self.assertEqual(self.gates, [[done, done]])


if __name__ == "__main__":
    unittest.main()
