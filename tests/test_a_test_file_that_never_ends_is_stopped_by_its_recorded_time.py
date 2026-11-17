"""A test file that runs far past the seconds its record gives it is stopped by
tests/every_file.py, its own process alone, though a process it left holds its output open: it
runs again alone, is stopped again and is named failed, whole where it ran whole, and the run ends
by itself; the parts it was asked for and had not ended run again and are named, as run and as
failed, beside one that named itself failing.  One the record gives no seconds of its own runs
on, and one taking a few times its record passes.

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
import time
import unittest

REPO = Path(__file__).resolve().parents[1]

# Notes the parts each run gives it and runs them, else those ACME_PARTS names: "acme" passes,
# timed in the file PART_TIMES names, "fix_api" fails, named in the file FAILED_PARTS names, and
# "hang" never ends, leaving ACME_LEFT holding its output; the others end after ACME_TAKES
# seconds.  Started in a group of its own, it fails; it ends once its runner is gone.
STAND_IN = '''import json, os, subprocess, sys, time
runner, asked = os.getppid(), sys.argv[1:]
assert os.getpgrp() == os.getpgid(runner), "started in a group of its own"
parts = asked or os.environ["ACME_PARTS"].split()
with open(os.environ["ACME_LOG"], "a") as fh:
    fh.write(" ".join(asked) + "\\n")
with open(os.environ["FAILED_PARTS"], "a") as fh:
    fh.writelines(f"{part}\\n" for part in parts if part == "fix_api")
with open(os.environ["PART_TIMES"], "w") as fh:
    json.dump({part: .1 for part in parts if part == "acme"}, fh)
ends = time.monotonic() + float(os.environ["ACME_TAKES"])
if "hang" in parts:
    subprocess.Popen([sys.executable, "-c", os.environ["ACME_LEFT"], str(runner)])
    ends = float("inf")
while time.monotonic() < ends and os.getppid() == runner:
    time.sleep(.05)
print("TESTS_RUN=1")
sys.exit("fix_api" in parts)
'''
# Holds the output it was started with until the runner, its argument, is gone; then notes it
# ended by itself.
LEFT = '''import os, sys, time
while True:
    try:
        os.kill(int(sys.argv[1]), 0)
    except OSError:
        break
    time.sleep(.05)
with open(os.environ["ACME_ENDED"], "a") as fh:
    fh.write("ended\\n")
'''
LEAST = 2
RUNNER = f'''import sys
sys.path.insert(0, sys.argv[1])
import every_file
every_file.LEAST = {LEAST}
sys.exit(every_file.main(every_file.Path(sys.argv[2])))
'''
ACME = "tests/test_acme.py"
PARTS = [f"{ACME}::{part}" for part in ("acme", "fix_api", "hang")]
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

    def every_file(self, record, parts="", takes=0, only=None):
        """every_file.py's run, handed `record`; the stand-in's runs are in ran.log."""
        (self.root / "times").write_text(json.dumps({"tests/test_widget.py": 0, **record}))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTKIT_", "AK_"))}
        env.update(HOME=str(self.root), ACME_LOG=str(self.root / "ran.log"), ACME_PARTS=parts,
                   ACME_TAKES=str(takes), ACME_LEFT=LEFT, ACME_ENDED=str(self.root / "ended"),
                   AK_FAILED=str(self.root / "failed"), AK_RAN=str(self.root / "ran"),
                   AK_TIMES=str(self.root / "times"), AK_CGROUP_FILE=str(self.root / "no-cgroup"),
                   AK_HOST_READINGS='{"cpu_pressure": 0, "free_mb": 4096}')
        if only is not None:
            (self.root / "only").write_text("".join(f"{test}\n" for test in only))
            env["AK_ONLY"] = str(self.root / "only")
        # A runner that never stops the file never ends: the ceiling fails it.
        return subprocess.run([sys.executable, "-c", RUNNER, str(REPO / "tests"), str(self.root)],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=120)

    def ended(self, count):
        """How many processes the stand-in left ended by themselves, waiting for `count`."""
        deadline = time.monotonic() + 60
        while len(self.read("ended")) < count and time.monotonic() < deadline:
            time.sleep(.05)
        return len(self.read("ended"))

    def test_a_file_that_never_ends_is_stopped_twice_and_named_whole(self):
        # It names a part failing before it hangs: the rest of it never ran.
        proc = self.every_file({ACME: 0.3}, parts="fix_api hang")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(len(STOPPED.findall(proc.stdout)), 2, proc.stdout)
        self.assertEqual((self.read("ran.log"), self.read("failed")), (["", ""], [ACME]))
        self.assertEqual(self.ended(2), 2)

    def test_its_parts_not_ended_run_again_and_are_named_beside_one_named_failing(self):
        proc = self.every_file(dict.fromkeys(PARTS, .1), only=PARTS)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.read("ran.log"), ["acme fix_api hang", "fix_api hang"])
        self.assertEqual(self.read("failed"), PARTS[1:])
        self.assertCountEqual(self.read("ran"), PARTS)
        self.assertEqual(self.ended(2), 2)

    def test_a_file_with_no_record_of_its_own_is_not_stopped(self):
        proc = self.every_file({}, takes=LEAST + 1)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.read("ran.log"), self.read("failed")), ([""], []))

    def test_a_file_taking_a_few_times_its_record_passes(self):
        proc = self.every_file({ACME: 0.3}, takes=1)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((self.read("ran.log"), self.read("failed")), ([""], []))


if __name__ == "__main__":
    unittest.main()
