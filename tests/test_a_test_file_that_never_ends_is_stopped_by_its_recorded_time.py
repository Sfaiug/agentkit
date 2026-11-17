"""A test file that runs far past the seconds its record gives it is stopped by
tests/every_file.py with what it started, runs again alone, is stopped again and is named failed,
and the run ends by itself; one the record gives no seconds of its own runs on, and one taking a
few times its record passes.

Offline: the real every_file.py, its minute (LEAST) lowered for this run alone, runs on a
temporary checkout of a stand-in noting each run, with injected host readings.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import host

# Starts a process that runs while the runner, its parent, does and notes its pid; then passes
# after ACME_TAKES seconds, "inf" never, or once the runner is gone.  The process ends quietly: a
# traceback's imports would write bytecode where the runner's cache was.
STAND_IN = '''import os, subprocess, sys, time
runner = os.getppid()
started = subprocess.Popen([sys.executable, "-c", "import os, sys, time\\ntry:\\n"
                            "    while not os.kill(int(sys.argv[1]), 0):\\n"
                            "        time.sleep(.05)\\nexcept OSError:\\n    pass",
                            str(runner)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
with open(os.environ["ACME_LOG"], "a") as fh:
    fh.write(f"{started.pid}\\n")
ends = time.monotonic() + float(os.environ["ACME_TAKES"])
while time.monotonic() < ends and os.getppid() == runner:
    time.sleep(.05)
print("TESTS_RUN=1")
'''
LEAST = 2
RUNNER = f'''import sys
sys.path.insert(0, sys.argv[1])
import every_file
every_file.LEAST = {LEAST}
sys.exit(every_file.main(every_file.Path(sys.argv[2])))
'''
ACME = "tests/test_acme.py"
STOPPED = re.compile(r"^(?:RETRY|FAIL ) tests/test_acme\.py: stopped after \d+s, "
                     r"the record giving it 0\.3s", re.MULTILINE)


class ATestFileThatNeverEndsIsStoppedByItsRecordedTime(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(
            prefix=".ak-test-stopped-", dir=REPO)))
        (self.root / "tests").mkdir()
        (self.root / "tests/smoke.sh").write_text("")
        (self.root / "tests/test_acme.py").write_text(STAND_IN)
        # On record at nothing: a file never measured is guessed at nothing a byte, and the
        # stop at LEAST would end one whose guess it took for a record.
        (self.root / "tests/test_widget.py").write_text('print("TESTS_RUN=1")\n')

    def read(self, name):
        path = self.root / name
        return path.read_text().splitlines() if path.exists() else []

    def every_file(self, takes, record):
        (self.root / "times").write_text(json.dumps({"tests/test_widget.py": 0, **record}))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(self.root), ACME_LOG=str(self.root / "ran.log"), ACME_TAKES=takes,
                   AK_FAILED=str(self.root / "failed"), AK_TIMES=str(self.root / "times"),
                   AK_CGROUP_FILE=str(self.root / "no-cgroup"),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        # A runner that never stops the file never ends: the ceiling fails it.
        return subprocess.run([sys.executable, "-c", RUNNER, str(REPO / "tests"), str(self.root)],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=120)

    def test_a_file_that_never_ends_is_stopped_twice_with_what_it_started_and_named(self):
        proc = self.every_file("inf", {ACME: 0.3})
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.read("failed"), [ACME])
        self.assertEqual(len(STOPPED.findall(proc.stdout)), 2, proc.stdout)
        started = self.read("ran.log")
        self.assertEqual(len(started), 2)
        self.assertFalse([pid for pid in map(int, started)
                          if (stat := host.proc_stat(pid)) is not None and not stat.exited])

    def test_a_file_with_no_record_of_its_own_is_not_stopped(self):
        proc = self.every_file(str(LEAST + 1), {})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((len(self.read("ran.log")), self.read("failed")), (1, []))

    def test_a_file_taking_a_few_times_its_record_passes(self):
        proc = self.every_file("1", {ACME: 0.3})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((len(self.read("ran.log")), self.read("failed")), (1, []))


if __name__ == "__main__":
    unittest.main()
