"""A run of every test on a change to Go alone runs only what that change can alter
(suite_shares.python_left_out): Go's tests with every claim, the static checks, each test file
whose code names Go's tree or imports one that does, and each block of smoke.sh that does; a
change anywhere else too, or none, runs all, and a live run every live check whatever the change.
Offline: the real landing.py, every_file.py and suite_shares.py run a stand-in git checkout whose
default branch, origin/HEAD, is its origin/main, and whose tests and blocks note that they ran.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from suite_shares import SETUP, STATIC_CHECKS

REPO = Path(__file__).resolve().parents[1]
NOTE = '''import os, pathlib, sys
if __name__ == "__main__":
    with open(os.environ["ACME_LOG"], "a") as fh:
        fh.write(" ".join([pathlib.Path(__file__).name, *sys.argv[1:]]) + "\\n")
    print("TESTS_RUN=1")
'''
SMOKE = f'''set -uo pipefail
if [ $# = 0 ]; then
  SMOKE_BODY=$(python3 {str(REPO / "tests/suite_shares.py")!r} tests/smoke.sh) || exit $?
  eval "$SMOKE_BODY"
  exit $?
fi
{SETUP}# --- alpha: a check reading Go's tree
cat go/acme.go >/dev/null && echo "smoke.sh#alpha" >>"$ACME_LOG"
# --- beta: a check of Python's alone, whose go/acme.go is prose
echo "smoke.sh#beta" >>"$ACME_LOG"
# --- 3: a live check of Python's alone, which only a live run runs
echo "smoke.sh#3" >>"$ACME_LOG"
'''
FILES = {
    "go/keys.txt": "test_key_acme\n",
    "go/acme.go": "package acme\n",
    "agentkit/acme.py": "",
    "tests/fixtures/acme.py": 'TREE = "go/acme.go"\n',
    "tests/smoke.sh": SMOKE,
    # the real runner, on the checkout landing.py hands it
    "tests/every_file.py": "import subprocess, sys\nsys.exit(subprocess.call([sys.executable, "
                           f"{str(REPO / 'tests/every_file.py')!r}, *sys.argv[1:]]))\n",
    **{f"tests/{name}.py": NOTE for name in (*STATIC_CHECKS, "gate_contract", "test_go",
                                             "test_go_keys", "test_key_acme")},
    "tests/test_acme_reads_go.py": NOTE + 'TREE = pathlib.Path(__file__).parents[1] / "go"\n',
    "tests/test_acme_imports_it.py": "import test_acme_reads_go\n" + NOTE,
    # a reader as a module of the checkout's root
    "tests/test_acme_imports_its_fixture.py": "import pathlib, sys\nsys.path.insert(0, str("
                                              "pathlib.Path(__file__).resolve().parents[1]))\n"
                                              "import tests.fixtures.acme\n" + NOTE,
    # Go's tree in prose only
    "tests/test_acme.py": '"""Judges what go/acme.go says."""\n# "go"\n' + NOTE,
}
ALL = {*(f"{name}.py" for name in STATIC_CHECKS), "test_go.py", "test_go_keys.py test_key_acme",
       "test_acme_reads_go.py", "test_acme_imports_it.py", "test_acme_imports_its_fixture.py",
       "test_acme.py", "test_key_acme.py", "gate_contract.py", "smoke.sh#alpha", "smoke.sh#beta"}


class AChangeToGoAloneRunsWhatReadsGo(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-go-alone-", dir=REPO)))
        self.root = self.sandbox / "acme"
        for name, text in FILES.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text)
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
            with open(self.root / name, "a") as fh:
                fh.write("\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def ran(self, *command, **env):
        """What a landing of the checkout runs, or `command` with `env`: each test as its file and
        arguments, each block of smoke.sh as `smoke.sh#<block>`."""
        log = self.sandbox / "ran.log"
        kept = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        done = subprocess.run(
            command or [sys.executable, REPO / "tests/landing.py"], cwd=self.root,
            env=dict(kept, **env, HOME=str(self.sandbox), ACME_LOG=str(log),
                     AK_CGROUP_FILE=str(self.sandbox / "no-cgroup"),
                     AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}'),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        ran = log.read_text().splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return set(ran)

    def test_a_change_to_go_alone_runs_go_the_static_checks_and_what_reads_go(self):
        for names in (["go/acme.go"], ["tests/test_go_keys.py"]):
            with self.subTest(names):
                self.change(*names)
                self.assertEqual(self.ran(), ALL - {"test_acme.py", "test_key_acme.py",
                                                    "gate_contract.py", "smoke.sh#beta"})

    def test_a_change_to_go_and_anything_else_runs_all(self):
        for name in ("agentkit/acme.py", "tests/fixtures/acme.py"):
            with self.subTest(name):
                self.change("go/acme.go", name)
                self.assertEqual(self.ran(), ALL)

    def test_a_checkout_on_its_base_runs_all(self):
        self.assertEqual(self.ran(), ALL)

    def test_a_live_run_on_a_change_to_go_alone_runs_every_live_check(self):
        self.change("go/acme.go")
        self.assertEqual(self.ran("bash", "tests/smoke.sh", AGENTKIT_SMOKE_LIVE="1"),
                         {"smoke.sh#3"})


if __name__ == "__main__":
    unittest.main()
