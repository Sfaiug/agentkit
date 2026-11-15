"""A run of every test judges Go only on what its change can alter (suite_shares.go_left_out): a
change to agentkit/ alone runs no Go test, one to a test file only the claims whose key file is or
imports it, Go's build with them, and one anywhere else, or none, all of Go's tests.
Offline: the real landing.py and every_file.py run a stand-in git checkout whose default branch,
origin/HEAD, is its origin/main, and whose static checks and Go's tests note what they were asked.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from suite_shares import STATIC_CHECKS

REPO = Path(__file__).resolve().parents[1]
NOTE = '''import os, pathlib, sys
if __name__ == "__main__":
    with open(os.environ["ACME_LOG"], "a") as fh:
        fh.write(" ".join([pathlib.Path(__file__).name, *sys.argv[1:]]) + "\\n")
    print("TESTS_RUN=1")
'''
FILES = {
    "go/keys.txt": "test_key_acme Acme\ntest_key_gadget\ntest_key_widget\n",
    "go/acme.go": "package acme\n",
    "agentkit/acme.py": "",
    "tests/fixtures/acme.py": "from . import rig\n",
    "tests/fixtures/rig.py": "from test_acme_base import *\n",
    "tests/smoke.sh": "",
    # the real runner, on the checkout landing.py hands it
    "tests/every_file.py": "import subprocess, sys\nsys.exit(subprocess.call([sys.executable, "
                           f"{str(REPO / 'tests/every_file.py')!r}, *sys.argv[1:]]))\n",
    **{f"tests/{name}.py": NOTE for name in (*STATIC_CHECKS, "gate_contract", "test_go",
                                             "test_go_keys", "test_key_acme", "test_key_gadget",
                                             "test_acme", "test_acme_base")},
    # a key reading a test file through another and a package of tests/
    "tests/test_key_widget.py": "import test_acme_rig\n" + NOTE,
    "tests/test_acme_rig.py": "import fixtures.acme\n" + NOTE,
}
ALL = {"tests/test_go.py", "tests/test_go_builds.py", "tests/test_go_keys.py::test_key_acme",
       "tests/test_go_keys.py::test_key_gadget", "tests/test_go_keys.py::test_key_widget"}


def write(root):
    for name, text in FILES.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


class GoRunsForWhatAChangeTouches(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-go-runs-", dir=REPO)))
        self.root = self.sandbox / "acme"
        write(self.root)
        self.git("init", "-q", "-b", "main")
        self.change()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    def git(self, *args):
        subprocess.run(["git", "-C", self.root, "-c", "user.name=acme",
                        "-c", "user.email=acme@example.com", *args], check=True,
                       capture_output=True)

    def change(self, *names):
        """A commit changing the files `names`."""
        for name in names:
            (self.root / name).write_text(f"{FILES[name]}# changed\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def go_run(self, root=None):
        """Of Go's tests, the IDs a landing of the checkout, or of the folder `root`, runs."""
        log = self.sandbox / "ran.log"
        kept = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        done = subprocess.run(
            [sys.executable, REPO / "tests/landing.py"], cwd=root or self.root,
            env=dict(kept, HOME=str(self.sandbox), ACME_LOG=str(log),
                     AK_CGROUP_FILE=str(self.sandbox / "no-cgroup"),
                     AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}'),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        ran = log.read_text().splitlines()
        log.unlink()
        return {f"tests/{name}{f'::{part}' if part else ''}"
                for name, *parts in map(str.split, ran) for part in parts or [""]
                if name in ("test_go.py", "test_go_builds.py", "test_go_keys.py")}

    def test_a_change_to_agentkit_alone_runs_no_go_test(self):
        self.change("agentkit/acme.py")
        self.assertEqual(self.go_run(), set())

    def test_a_change_to_a_claimed_key_runs_its_claims_and_no_other(self):
        # a test file no claimed key reads adds none
        self.change("tests/test_key_acme.py", "tests/test_acme.py")
        self.assertEqual(self.go_run(),
                         {"tests/test_go_builds.py", "tests/test_go_keys.py::test_key_acme"})

    def test_a_change_to_a_test_file_a_claimed_key_imports_runs_its_claims(self):
        self.change("tests/test_acme_base.py")
        self.assertEqual(self.go_run(),
                         {"tests/test_go_builds.py", "tests/test_go_keys.py::test_key_widget"})

    def test_a_change_to_go_or_to_the_fixtures_runs_all(self):
        for name in ("go/acme.go", "tests/fixtures/acme.py"):
            with self.subTest(name):
                self.change(name, "agentkit/acme.py")
                self.assertEqual(self.go_run(), ALL)

    def test_a_checkout_on_its_base_runs_all(self):
        self.assertEqual(self.go_run(), ALL)
        with self.subTest("a default branch other than main"):
            self.change("agentkit/acme.py")
            self.git("update-ref", "refs/remotes/origin/trunk", "HEAD")
            self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
            self.assertEqual(self.go_run(), ALL)

    def test_a_folder_inside_a_checkout_is_none_of_its_own_and_runs_all(self):
        # git there answers for the checkout, whose change is not the folder's
        self.change("agentkit/acme.py")
        write(self.root / "stand-in")
        self.assertEqual(self.go_run(self.root / "stand-in"), ALL)


if __name__ == "__main__":
    unittest.main()
