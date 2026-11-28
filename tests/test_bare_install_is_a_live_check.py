"""A version is installed on a bare machine before it goes live, where docker answers.

tests/live.sh holds check 52, which passes or fails as tests/bare-install.sh exits, run in the
checkout with the docker config of the HOME the run started in, only where `docker` and
`timeout` are on PATH and `timeout -k 5 20 docker info` exits 0, asked once as the run chooses
its checks.  Anywhere else it leaves 52 out by name, as AK_LIVE_NO_MODEL_CALLS=1 leaves the model
calls, no skip, so the run passes under AGENTKIT_ACCEPTANCE_REQUIRED=1.  A failed 52 is named in
the file AK_LIVE_FAILED names.  Offline: the entry runs on a stand-in suite, a passing fixture
per real check but 52's real block, in a temporary checkout whose bare-install.sh, and the
PATH's docker and timeout, are fakes that say they ran.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import suite_shares as suite

SMOKE = (REPO / "tests/smoke.sh").read_text()
BLOCKS = suite.smoke_blocks(SMOKE)
PROBE, INFO = "timeout -k 5 20 docker info", "docker info"
INSTALL = "bare-install {root} {root}/.docker"
DOCKER = {"docker": "exit 0", "timeout": 'shift 3; exec "$@"'}     # docker answers, in time
# a host: what its docker and timeout do, none where it has none; whether the run makes no model
# calls; the calls made; 52's verdict, as bare-install.sh exits, None where the run leaves it out
HOSTS = (
    ("docker answers", DOCKER, False, [PROBE, INFO, INSTALL], "PASS"),
    ("the install fails", DOCKER, False, [PROBE, INFO, INSTALL], "FAIL"),
    ("no model calls", DOCKER, True, [PROBE, INFO, INSTALL], "PASS"),
    ("no docker", {"timeout": "exit 0"}, False, [], None),
    ("no timeout", {"docker": "exit 0"}, False, [], None),
    ("docker info exits 1", {**DOCKER, "docker": "exit 1"}, False, [PROBE, INFO], None),
    ("docker info runs out of time", {**DOCKER, "timeout": "exit 124"}, False, [PROBE], None),
    ("no docker, no model calls", {"timeout": "exit 0"}, True, [], None),
)


class BareInstallIsALiveCheck(unittest.TestCase):
    def live_run(self, fakes, no_model_calls, verdict):
        """The stand-in checkout, its tests/live.sh run there, and the calls the fakes made."""
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-bare-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        for name in ("live.sh", "suite_shares.py", "acceptance.sh"):
            shutil.copy(REPO / "tests" / name, root / "tests")
        # the real entry and setup, a sandbox HOME as smoke_home makes, then a passing fixture per
        # real check but 52, whose block is the real one
        stub = SMOKE[:SMOKE.index('export PATH="$REPO/bin:$PATH"')]
        stub += ('SMOKE_CALLER_HOME=$HOME; WORK="$HOME/work"; HOME="$WORK/home"\n'
                 'mkdir -p "$HOME"; . "$REPO/tests/acceptance.sh"\n')
        stub += "".join(body if name == "52" else f"# --- {name}: fixture\nok '{name}'\n"
                        for name, body in BLOCKS if name is not None)
        (root / "tests/smoke.sh").write_text(stub + "# --- shared result ---\nfinish\n")
        (root / "tests/bare-install.sh").write_text(
            f'echo "bare-install $PWD $DOCKER_CONFIG" >>"$CALLS"; exit {int(verdict == "FAIL")}\n')
        # a PATH of the tools the stand-in runs, and of this host's fakes
        tools = root / "bin"
        tools.mkdir()
        for tool in ("bash", "dirname", "mkdir", "cat", "mv", "rm"):
            (tools / tool).symlink_to(shutil.which(tool))
        (tools / "python3").symlink_to(sys.executable)
        for fake, does in fakes.items():
            (tools / fake).write_text(f'#!/bin/sh\necho "{fake} $*" >>"$CALLS"; {does}\n')
            (tools / fake).chmod(0o755)
        calls = root / "calls"
        env = {"HOME": str(root), "PATH": str(tools), "CALLS": str(calls),
               "AK_LIVE_FAILED": str(root / "failed"), "AGENTKIT_ACCEPTANCE_REQUIRED": "1",
               "AK_LIVE_NO_MODEL_CALLS": str(int(no_model_calls))}
        # from tests/, so 52 must find the checkout itself
        proc = subprocess.run([str(tools / "bash"), "live.sh"], cwd=root / "tests", env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        return root, proc, calls.read_text().splitlines() if calls.exists() else []

    def test_a_live_run_holds_52_where_docker_answers(self):
        for host, fakes, no_model_calls, calls, verdict in HOSTS:
            with self.subTest(host):
                root, proc, made = self.live_run(fakes, no_model_calls, verdict)
                out = proc.stdout + proc.stderr
                self.assertEqual(proc.returncode, int(verdict == "FAIL"), out)
                self.assertEqual(made, [call.format(root=root) for call in calls])
                # every verdict printed, a skip's too, each check's once
                ran = sorted(re.findall(r"(?m)^(PASS|FAIL|SKIP)  (\w+)", proc.stdout))
                held = suite.LIVE_CHECKS - {"52"} - (suite.MODEL_CALLS if no_model_calls else set())
                want = [("PASS", name) for name in held] + ([(verdict, "52")] if verdict else [])
                self.assertEqual(ran, sorted(want), out)
                self.assertIn(", 0 skipped", proc.stdout)
                failed = ["52"] if verdict == "FAIL" else []
                self.assertEqual((root / "failed").read_text().split(), failed)


if __name__ == "__main__":
    unittest.main()
