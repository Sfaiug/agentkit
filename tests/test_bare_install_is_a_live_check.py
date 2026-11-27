"""A version is installed on a bare machine before it goes live, where docker answers.

tests/live.sh holds check 52, which passes or fails as tests/bare-install.sh exits, run in the
checkout with the docker config of the HOME the run started in, only where `timeout -k 5 20
docker info` exits 0, asked once as the run chooses its checks.  Anywhere else it leaves 52 out
by name, no skip, so the run passes under AGENTKIT_ACCEPTANCE_REQUIRED=1.  Offline: the entry
runs on a stand-in suite, a passing fixture per real check but 52's real block, in a temporary
checkout whose bare-install.sh, and the PATH's docker and timeout, are fakes that say they ran.
"""

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
PROBE = "timeout -k 5 20 docker info"
INSTALL = "bare-install {root} {root}/.docker"
# a host: the fakes on its PATH, what `docker info` and bare-install.sh exit there, the calls
# made, and 52's verdict, None where the run leaves it out
HOSTS = (
    ("docker answers", ("docker", "timeout"), 0, 0, [PROBE, "docker info", INSTALL], "PASS"),
    ("the install fails", ("docker", "timeout"), 0, 1, [PROBE, "docker info", INSTALL], "FAIL"),
    ("no docker", ("timeout",), 0, 0, [PROBE], None),
    ("no timeout", ("docker",), 0, 0, [], None),
    ("docker info exits 1", ("docker", "timeout"), 1, 0, [PROBE, "docker info"], None),
)


class BareInstallIsALiveCheck(unittest.TestCase):
    def live_run(self, fakes, info, install):
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
            f'echo "bare-install $PWD $DOCKER_CONFIG" >>"$CALLS"; exit {install}\n')
        # a PATH of the tools the stand-in runs, and of this host's fakes
        tools = root / "bin"
        tools.mkdir()
        for tool in ("bash", "dirname", "mkdir", "cat"):
            (tools / tool).symlink_to(shutil.which(tool))
        (tools / "python3").symlink_to(sys.executable)
        does = {"docker": f"exit {info}", "timeout": 'shift 3; exec "$@"'}
        for fake in fakes:
            (tools / fake).write_text(f'#!/bin/sh\necho "{fake} $*" >>"$CALLS"; {does[fake]}\n')
            (tools / fake).chmod(0o755)
        calls = root / "calls"
        env = {"HOME": str(root), "PATH": str(tools), "CALLS": str(calls),
               "AGENTKIT_ACCEPTANCE_REQUIRED": "1"}
        # from tests/, so 52 must find the checkout itself
        proc = subprocess.run([str(tools / "bash"), "live.sh"], cwd=root / "tests", env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        return root, proc, calls.read_text().splitlines() if calls.exists() else []

    def test_a_live_run_holds_52_where_docker_answers(self):
        for host, fakes, info, install, calls, verdict in HOSTS:
            with self.subTest(host):
                root, proc, made = self.live_run(fakes, info, install)
                out = proc.stdout + proc.stderr
                self.assertEqual(proc.returncode, int(verdict == "FAIL"), out)
                self.assertEqual(made, [call.format(root=root) for call in calls])
                ran = {line.split()[1]: line[:4] for line in proc.stdout.splitlines()
                       if line.startswith(("PASS  ", "FAIL  "))}
                held = dict.fromkeys(suite.LIVE_CHECKS - {"52"}, "PASS")
                self.assertEqual(ran, held | ({"52": verdict} if verdict else {}), out)
                self.assertIn(", 0 skipped", proc.stdout)


if __name__ == "__main__":
    unittest.main()
