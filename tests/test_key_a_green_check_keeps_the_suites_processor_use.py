"""A green whole check keeps on each command's cost, in the one write of its length
(`gate.green_seconds`), the processors the command used on this host through the check
(`gate.green_cpus`): the CPU seconds all its check rows count, a go its re-run decided
included, over that length.  A red check after it leaves both as they were.

Black-box: the program `AK_BIN` names checks a landing line through tests/fixtures/akline.py,
its suite's one test, or a member's `# once` command on its first go, burning half a
processor-second, and the test reads the command's cost where ak keeps it.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import SUITE, Line

# this test's own Python, never one found on PATH (test_key_check_records_cpu_and_memory.py)
BURN = (shlex.quote(sys.executable) + " -c \"import time; "
        "any(time.process_time() >= .5 for _ in iter(int, 1))\"\n")
# red on its first go, which burns, and green on its re-run, which does not
RETRIED = "sh retry.sh"
RETRY = ('mark="$(git rev-parse --git-common-dir)/burned"\n'
         'test -e "$mark" && exit 0\ntouch "$mark"\n' + BURN + "exit 1\n")


class AGreenCheckKeepsTheSuitesProcessorUse(unittest.TestCase):
    def setUp(self):
        self.line = Line({"t/burn.sh": "test ! -f red.txt || exit 1\n" + BURN})
        self.addCleanup(self.line.close)

    def landed(self, files, once=None):
        """The next member, its branch adding `files` and its task's `# once` command `once`,
        checked in one pass; its verdict."""
        self.line.member(files)
        if once:
            (self.line.members[-1] / "task.md").write_text(
                f"# fix\n\n## Done when\n```bash\n{once}  # once\n```\n")
        done = self.line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return self.line.verdict(len(self.line.members))

    def kept(self, command=SUITE):
        """The length and the use `command`'s cost keeps, and that cost whole."""
        cost = json.loads(self.line.cost_of(command).read_text())
        return (cost["green_seconds"], cost.get("green_cpus", 0)), cost

    def test_a_green_check_keeps_the_use_and_a_red_one_after_it_leaves_it(self):
        self.assertIn("land", self.landed({"api.txt": "x\n"}))
        (seconds, cpus), cost = self.kept()
        self.assertGreaterEqual(seconds * cpus, .5, cost)
        self.assertIn("fix", self.landed({"red.txt": "x\n"}))
        self.assertEqual(self.kept()[0], (seconds, cpus))

    def test_a_go_its_re_run_decided_counts_too(self):
        self.assertIn("land", self.landed({"retry.sh": RETRY}, RETRIED))
        (seconds, cpus), cost = self.kept(RETRIED)
        self.assertGreaterEqual(seconds * cpus, .5, cost)


if __name__ == "__main__":
    unittest.main()
