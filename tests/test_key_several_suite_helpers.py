"""A suite goes to the machine ak may use with the most room, any named under `[machines]`.
Black-box through tests/fixtures/akline.py; a fake ssh is the machines."""

import sys
import unittest
from fixtures import akconfig
from fixtures.akline import Line

SSH = f"""#!{sys.executable}
import shlex, sys
verb = shlex.split(sys.argv[-1])[4]    # bash -c <mac.sh> mac.sh <verb> ...
if verb == "probe":
    print("cpus", dict(full=2, some=4, most=8)[sys.argv[-2]], "\\nload 2\\nroom_mb 65536")
"""


class SeveralSuiteHelpers(unittest.TestCase):
    def test_a_suite_goes_to_the_machine_with_the_most_room(self):
        line = Line({"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM acme\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus"], extra="[machines.full]\n[machines.some]\n[machines.most]")
        line.home.fake("ssh", SSH)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertIn("suite on most:", done.out + done.err)
        self.assertIn("land", line.verdict(1))


if __name__ == "__main__":
    unittest.main()
