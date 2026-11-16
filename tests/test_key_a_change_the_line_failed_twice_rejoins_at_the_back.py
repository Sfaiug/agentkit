"""A change the line's check failed twice rejoins at the back; its first repair keeps its place.

A run's work goes red in its line, and its first repair is red again: rejoining after that
first repair, it is still ahead of the members that joined behind it; rejoining after the
second, it is behind them, and it merges once green.  Black-box: the program `AK_BIN` names
runs the task from outside through tests/fixtures/akbin.py on the project and suite of
tests/fixtures/akline.py, unsplit, with harnesses from fakeadapter.py and the GitHub of
fakegh.py.  The members behind it are records of a live process of this test's, which the
line's check skips, so they keep their places.  The suite holds its check of each repaired
tree until the test has read the line's records.
"""

import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter, taskfile
from fixtures.akbin import owner
from test_key_a_passed_run_joins_the_line_unchecked import record, staged

# The check of a tree holding `tried.txt`, then of one holding `fixed.txt`, waits for its go.
HELD = 'own="$(git rev-parse --git-common-dir)"\nfor step in tried fixed; do\n' \
       '  if [ -f "$step.txt" ] && [ ! -f "$own/$step-go" ]; then : >"$own/$step-held"\n' \
       '    until [ -f "$own/$step-go" ]; do sleep 0.1; done; fi\ndone\n'
WORK = {**fakeadapter.WORK, "write": {"retry.txt": "hello\n", "bad.txt": "x\n"}}
TRIED = {"write": {"tried.txt": "x\n"}, "commit": "try again",
         "final": "## Summary\ntried again", "hand_in": [["done"]]}
FIXED = {"write": {"fixed.txt": "x\n"}, "sh": "git rm -q bad.txt", "commit": "remove bad.txt",
         "final": "## Summary\nremoved bad.txt", "hand_in": [["done"]]}


class FailedTwiceRejoinsAtTheBack(unittest.TestCase):
    def until(self, test, ran):
        deadline = time.monotonic() + 300
        while not test():
            self.assertLess(time.monotonic(), deadline, "the run never got there")
            self.assertIsNone(ran.poll(), self.line.home.log("spawn-1.err").read_text())
            time.sleep(0.1)
        return test()

    def write(self, member, **changes):
        path = member / "run.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({**json.loads(path.read_text()), **changes}))
        temp.replace(path)

    def test_the_second_repair_rejoins_behind_those_that_waited(self):
        self.line = line = staged(self, {"t/ok.sh": "true\n", "t/bad.sh": "test ! -f bad.txt\n",
                                         "t/held.sh": HELD}, claude=[WORK, TRIED, FIXED])
        for n in (1, 2):
            line.member({f"member-{n}.txt": f"{n}\n"})
            proc = subprocess.Popen(["cat"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
            self.addCleanup(proc.wait)
            self.addCleanup(proc.stdin.close)
            self.write(line.members[-1], **owner(proc.pid))
        own = line.rig.path / ".git"
        ran = line.home.spawn("run", str(taskfile.write(line.home, line.rig.path)))
        run = self.until(lambda: [path for path in taskfile.runs(line.home)
                                  if path not in line.members], ran)[0]
        first = self.until(lambda: (read(run).get("waiting_on") or {}).get("joined"), ran)
        # they join behind it
        behind = [time.time() for _ in line.members]
        for member, joined in zip(line.members, behind):
            self.write(member, waiting_on={"line": line.line, "joined": joined})
        self.until((own / "tried-held").exists, ran)
        self.assertEqual(read(run)["waiting_on"]["joined"], first)
        self.assertLess(first, min(behind))
        (own / "tried-go").touch()
        self.until((own / "fixed-held").exists, ran)
        self.assertGreater(read(run)["waiting_on"]["joined"], max(behind))
        (own / "fixed-go").touch()
        self.assertEqual(ran.wait(timeout=300), 0, line.home.log("spawn-1.err").read_text())
        self.assertTrue(read(run).get("merged"))
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()],
                         ["executor", "fixer", "fixer"])


def read(run):
    """The run's record, or {} before it has one."""
    try:
        return record(run)
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    unittest.main()
