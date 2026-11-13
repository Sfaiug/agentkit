"""A check that ends red leaves its suite's measured cost as it was: only a pass that ended green
measures what one piece needs, and a red one records how long it took and no more.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py, its suite split
into pieces, on a host whose readings (AK_HOST_READINGS) give each box a day of waiting for a
core: a pass that measures records its own seconds' share of that day, so no two record the
same.  The cost is read where ak keeps it, in its state.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

READINGS = {"AK_HOST_READINGS": json.dumps(
    {"cpus": 4, "load": 0, "free_mb": 16000, "cpu_wait_seconds": 86400})}
NEEDS = ("cpus", "mem_mb")      # what one piece needs, as the next check's pieces are charged


class ARedCheckLeavesTheSuitesCostAsItWas(unittest.TestCase):
    def cost_after(self, line, files, verdict):
        """The suite's cost on record once the lander gave a new member adding `files` that
        `verdict`."""
        line.member(files)
        done = line.home.ak("run", "--lander", line.line, timeout=600, env=READINGS)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(verdict, line.verdict(len(line.members)))
        [cost] = (json.loads(path.read_text())
                  for path in (line.home.path / ".agentkit" / "state").glob("suite-*.json"))
        return cost

    def test_only_a_green_check_records_what_a_piece_needs(self):
        line = Line({"t/a.sh": "test ! -f red.txt\n"})
        self.addCleanup(line.close)
        first = self.cost_after(line, {"red.txt": "x\n"}, "fix")
        self.assertIn("wall_seconds", first)
        self.assertFalse(set(NEEDS) & set(first), first)
        green = self.cost_after(line, {"fix.txt": "x\n"}, "land")
        self.assertIn("cpus", green)
        red = self.cost_after(line, {"red.txt": "x\n"}, "fix")
        self.assertEqual([red.get(need) for need in NEEDS],
                         [green.get(need) for need in NEEDS])


if __name__ == "__main__":
    unittest.main()
