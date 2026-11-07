"""A red's part the target's tip does not have proves nothing when the tip is probed with the
red's failed tests alone (`gate.run_suite(only=, confirmed=)`, as `land._probe_tip` asks): a Go
test, or a package run whole, whose package the tip lacks, a Go test its package lacks, a claim
its go/keys.txt lacks.  A part the tip has that fails, in either runner, is the tip's own red.

Offline: the real every_file.py, test_go.py and test_go_keys.py judge a temporary tip in a real
check box, each file's parts in one run as a measured suite cuts them, with a stand-in `go` and
key, injected host readings and a sandbox HOME and state.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import REPO, Sandbox
from agentkit import gate, suite_times

ACME, GONE = "agentkit/internal/acme", "agentkit/internal/gone"
GO_TESTS, CLAIMS = "tests/test_go.py", "tests/test_go_keys.py"
# Go, for a module whose one package, acme, holds one test, TestFixApi, which fails: a package
# it cannot find fails as Go's setup does, and a test acme lacks runs none.
GO = f'''#!{sys.executable}
import json, sys
args = sys.argv[1:]
if args[:2] == ["env", "-json"]:
    print(json.dumps({{"GOROOT": "/nonexistent", "GOOS": "linux", "GOARCH": "amd64"}}))
elif args[0] == "test":
    package = args[-1]
    def event(action, **more):
        print(json.dumps({{"Action": action, "Package": package, **more}}))
    if package != "{ACME}":
        print(json.dumps({{"ImportPath": package, "Action": "build-fail"}}))
        event("fail", FailedBuild=package)
        sys.exit(1)
    if "-run" in args and "^TestFixApi$" not in args:
        event("pass")
    else:
        event("run", Test="TestFixApi")
        event("fail", Test="TestFixApi")
        event("fail")
        sys.exit(1)
'''
KEY = '''import unittest
class Acme(unittest.TestCase):
    def test_it(self):
        self.fail("acme broke")
unittest.main()
'''


class APartTheTipLacksProvesNothing(Sandbox):
    def setUp(self):
        super().setUp()
        self.tip = self.root / "tip"
        (self.tip / "tests").mkdir(parents=True)
        for name in ("test_go.py", "test_go_keys.py", "suite_shares.py"):
            shutil.copy(REPO / "tests" / name, self.tip / "tests")
        (self.tip / "tests/test_key_acme.py").write_text(KEY)
        (self.tip / "go/internal/acme").mkdir(parents=True)
        (self.tip / "go/internal/acme/acme_test.go").write_text(
            'package acme\n\nimport "testing"\n\n'
            'func TestFixApi(t *testing.T) { t.Fatal("acme broke") }\n')
        (self.tip / "go/go.mod").write_text("module agentkit\n\ngo 1.23.0\n\ntoolchain go1.23.0\n")
        (self.tip / "go/keys.txt").write_text("test_key_acme Acme\n")
        (self.root / "bin").mkdir()
        (self.root / "bin/go").write_text(GO)
        (self.root / "bin/go").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "AK_HOST_READINGS": '{"cpu_pressure": 0, "free_mb": 4096}',
            "AK_CGROUP_FILE": str(self.root / "no-cgroup")}))
        # Measured, each file's parts share one run, a part never timed at its file's mean.
        measured = self.root / "measured.log"
        measured.write_text("".join(f"{suite_times.passed(test, 1)}\n" for test in (
            f"{GO_TESTS}::{ACME}.TestFixApi", f"{CLAIMS}::test_key_acme")))
        suite_times.keep(self.tip, measured)

    def probe(self, red):
        """The tests of `red` the tip's probe confirms as its own red, by share."""
        confirmed, activity = {}, self.root / "probe.log"
        with activity.open("w+b") as output:
            gate.run_suite(f"{sys.executable} {REPO / 'tests/every_file.py'} .", 600,
                           cwd=self.tip, activity=activity, output=output, shard="1/1",
                           only=red, confirmed=confirmed, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL)
        return confirmed

    def test_only_a_part_the_tip_has_that_fails_is_its_own_red(self):
        for gone in (f"{GONE}.TestFixApi", GONE):
            for own in (f"{GO_TESTS}::{ACME}.TestFixApi", f"{CLAIMS}::test_key_acme"):
                with self.subTest(gone=gone, own=own):
                    red = [f"{GO_TESTS}::{gone}", f"{GO_TESTS}::{ACME}.TestGone",
                           f"{CLAIMS}::test_key_gone", own]
                    self.assertEqual(self.probe(red), {"1/1": [own]},
                                     (self.root / "probe.log").read_text())


if __name__ == "__main__":
    unittest.main()
