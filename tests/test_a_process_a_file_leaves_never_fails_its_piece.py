"""A process a test file leaves behind, still writing into its HOME and the piece's bytecode
cache while tests/every_file.py removes them, never fails the piece: the file passed.

Offline: the real every_file.py runs on a temporary checkout holding one stand-in, which
leaves a process writing new files into both until every_file.py has exited.  The host
readings are injected.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]

# Writes until the runner, its argument, is gone; then removes the HOME it may have left in
# /tmp and notes that it stopped.
LEFT = '''import os, pathlib, shutil, sys, time
runner, home = int(sys.argv[1]), pathlib.Path(os.environ["HOME"])
cache = pathlib.Path(os.environ["PYTHONPYCACHEPREFIX"])
deadline, count = time.monotonic() + 60, 0
while time.monotonic() < deadline:
    try:
        os.kill(runner, 0)
    except OSError:
        break
    count += 1
    for directory in (home, cache):
        try:
            (directory / f"late-{count}").touch()
        except FileNotFoundError:
            pass
shutil.rmtree(home, ignore_errors=True)
pathlib.Path("stopped").touch()
'''
STAND_IN = f'''import os, pathlib, subprocess, sys, time
subprocess.Popen([sys.executable, "-c", {LEFT!r}, str(os.getppid())],
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while not (pathlib.Path(os.environ["PYTHONPYCACHEPREFIX"]) / "late-5000").exists():
    time.sleep(.01)
print("TESTS_RUN=1")
'''


class AProcessAFileLeavesNeverFailsItsPiece(unittest.TestCase):
    def test_a_file_whose_process_writes_on_as_its_sandboxes_go_passes(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-left-process-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        tests = root / "tests"
        tests.mkdir()
        (tests / "smoke.sh").write_text("")
        (tests / "test_acme.py").write_text(STAND_IN)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(root), AK_CGROUP_FILE=str(root / "no-cgroup"),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        proc = subprocess.run([sys.executable, str(REPO / "tests/every_file.py"), str(root)],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=120)
        deadline = time.monotonic() + 60
        while not (root / "stopped").exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS  tests/test_acme.py", proc.stdout)


if __name__ == "__main__":
    unittest.main()
