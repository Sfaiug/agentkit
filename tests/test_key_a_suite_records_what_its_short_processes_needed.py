"""A suite's recorded cost counts what its processes needed, however short they lived: a process
that starts and ends between two of its box's looks counts as much as one that stays.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py whose `tests:` line
is one command, no pieces, on this host's own readings: injected ones (`AK_HOST_READINGS`)
would stand in for what its box counts.  The command keeps four chains of short processes going
on one core, so they ask for about four times what they get, and writes what they spent.  The
cost the check leaves in ak's state, CPU seconds a second its box ran, holds at least twice what
they spent a second of the check (`wall_seconds`), which outlasts the box.  A busier host only
widens the gap.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, rules

# Pinned, with all it starts, to one core of those it may use, each chain starts a process that
# burns a few hundredths of a second of its own CPU and ends, again and again for six seconds;
# then it prints what its children spent.  Its threads' name is no UTF-8: Linux takes any bytes.
CHAINS = r'''import ctypes, os, resource, subprocess, sys, threading, time
ctypes.CDLL(None).prctl(15, b"acme\xff", 0, 0, 0)   # PR_SET_NAME
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
end = time.monotonic() + 6
def chain():
    while time.monotonic() < end:
        subprocess.run([sys.executable, "-S", "-c",
                        "import time\nwhile time.process_time() < 0.03: pass"])
chains = [threading.Thread(target=chain) for _ in range(4)]
for one in chains:
    one.start()
for one in chains:
    one.join()
spent = resource.getrusage(resource.RUSAGE_CHILDREN)
print(spent.ru_utime + spent.ru_stime)
'''


class ASuiteRecordsWhatItsShortProcessesNeeded(unittest.TestCase):
    def test_short_processes_sharing_a_core_record_more_than_they_spent(self):
        suite = 'python3 chains.py >"$(git rev-parse --git-common-dir)/spent"'
        line = Line({"AGENTS.md": rules(suite), "chains.py": CHAINS})
        self.addCleanup(line.close)
        line.member({"fix-1.txt": "x\n"})
        done = line.home.ak("run", "--lander", line.line, timeout=600)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("land", line.verdict(1))
        spent = float((line.rig.path / ".git" / "spent").read_text())
        self.assertGreater(spent, 0)
        [cost] = (json.loads(path.read_text())
                  for path in (line.home.path / ".agentkit" / "state").glob("suite-*.json"))
        self.assertGreaterEqual(cost["cpus"], 2 * spent / cost["wall_seconds"], cost)


if __name__ == "__main__":
    unittest.main()
