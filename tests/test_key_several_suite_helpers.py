"""A suite goes to the machine ak may use with the most room, any named under `[machines]`, and to
the next where that one turns it away. Black-box through tests/fixtures/akline.py; a fake ssh is
the machines."""

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

# Another suite took the machine's room between the probe and `prepare`.
TURNED_AWAY = SSH + """if verb == "prepare" and sys.argv[-2] == "most":
    sys.exit(252)
"""

# Each fits all a suite may take; one named later has the most spare beyond that.
SPARE = f"""#!{sys.executable}
import shlex, sys
verb = shlex.split(sys.argv[-1])[4]
if verb == "probe":
    print("cpus 8\\nload 0\\nroom_mb 65536\\nspare", dict(full=9, some=16, most=12)[sys.argv[-2]])
"""


class SeveralSuiteHelpers(unittest.TestCase):
    def landed(self, ssh):
        line = Line({"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM acme\n"})
        self.addCleanup(line.close)
        akconfig.write(line.home, ["opus"], extra="[machines.full]\n[machines.some]\n[machines.most]")
        line.home.fake("ssh", ssh)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertIn("land", line.verdict(1))
        return done.out + done.err

    def test_a_suite_goes_to_the_machine_with_the_most_room(self):
        self.assertIn("suite on most:", self.landed(SSH))

    def test_machines_that_each_fit_the_suite_go_by_what_is_spare(self):
        self.assertIn("suite on some:", self.landed(SPARE))

    def test_a_machine_turning_the_suite_away_sends_it_to_the_next(self):
        said = self.landed(TURNED_AWAY)
        self.assertIn("suite on some:", said)
        self.assertNotIn("suite runs here", said)


if __name__ == "__main__":
    unittest.main()
