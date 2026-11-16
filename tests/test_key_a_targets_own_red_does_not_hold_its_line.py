"""A target's own red does not hold its line while its repair is under way.

The target's tip fails t/widget.sh alone, by name, so the lander starts its repair at once.
While that is under way the members whose stack is red in nothing else land over it, no green
evidence kept for their trees, and one red in t/acme.sh too gets a fix naming that test alone,
widget.sh excused, as a fix given while the target was still green is once its red is found.
The landings over it keep no red of widget.sh in history: that red is the tip's, kept there.
The repair, once its stack passes widget.sh, lands with the `Suite-Passed-Tree` trailer, and the
target's new tip holds no red.  A red that named no test holds the line on the retry ladder.
Black-box: the program `AK_BIN` names checks the line from outside through
tests/fixtures/akline.py, its suite failing before it names a test where crash.txt is, the
repair's worker scripted by fakeadapter.py and its GitHub by fakegh.py.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akline import READINGS, RUNNER, Line
from fixtures.fakegh import GitHub
from test_key_history_db import read
from test_key_landing_and_health_leave_rows import started

TESTS = {"suite.sh": "test ! -f crash.txt || exit 1\n" + RUNNER, "t/ok.sh": "true\n",
         "t/widget.sh": "test -f retry.txt\n", "t/acme.sh": "test ! -f acme.txt\n"}


def record(run):
    return json.loads((run / "run.json").read_text())


class ATargetsOwnRedDoesNotHoldItsLine(unittest.TestCase):
    def line(self, **files):
        line = Line({**TESTS, **files})
        self.addCleanup(line.close)
        line.home.env.update(AK_HOST_READINGS=READINGS)
        line.home.write(".agentkit/state/session-seat.json",
                        {"orchestrator": "opus", "workers": ["opus"]})
        return line

    def member(self, line, files):
        """Park the line's next member, launched from the seat a repair it starts is given."""
        line.member(files)
        path = line.members[-1] / "run.json"
        path.write_text(json.dumps({**record(line.members[-1]), "launched_session": "seat"}))

    def land(self, line):
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)

    def green(self, line):
        """The line's evidence: green `trees` and the target's `red` entries, by tree."""
        return json.loads((line.members[0].parent / line.line).with_suffix(".green").read_text())

    def test_members_land_over_the_targets_named_red_and_its_repair_lands_green(self):
        line = self.line()
        GitHub(line.home).grant(line.rig.slug, "WRITE")
        akconfig.write(line.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        worker = fakeadapter.install(line.home, claude="work", codex="pass")["claude"]
        # the repair writes the retry.txt the target lacks, committed once the test lets it
        release = worker.dir / "release"
        worker.behave({**fakeadapter.WORK, "sh": f"until [ -f '{release}' ]; do sleep 0.1; done"})
        started(line.home, "fix-1", "fix-2", "fix-3")
        for files in ({"one.txt": "1\n"}, {"two.txt": "2\n"}):
            self.member(line, files)
        self.land(line)
        repair, = (path for path in line.members[0].parent.iterdir()
                   if path.is_dir() and path not in line.members)
        self.member(line, {"acme.txt": "red\n"})
        self.land(line)
        for n in (1, 2):
            verdict = line.verdict(n)
            self.assertEqual(verdict["over"], ["widget.sh"], verdict)
            self.assertNotIn(verdict["land"], self.green(line)["trees"])
        fix = line.verdict(3)["fix"]
        self.assertEqual((fix["tests"], fix["excused"]), (["acme.sh"], ["widget.sh"]))
        kept = read(line.home, "SELECT DISTINCT test FROM test_reds WHERE run_id='fix-3' "
                               "AND kind='landing'")
        self.assertEqual([row["test"] for row in kept], ["acme.sh"])
        # the two delivered (their resumes here refuse), the repair is checked as any member
        for member in line.members[:2]:
            (member / "run.json").write_text(json.dumps({**record(member), "state": "pass",
                                                         "merged": True}))
        release.touch()
        deadline = time.monotonic() + 600
        while not record(repair).get("merged"):
            self.assertLess(time.monotonic(), deadline, "the repair never merged")
            time.sleep(0.2)
        tree = line.rig.origin("rev-parse", "main^{tree}")
        self.assertTrue(line.rig.origin("log", "-1", "--format=%b", "main").endswith(
            f"Suite-Passed-Tree: {tree}"))
        self.assertNotIn(tree, self.green(line)["red"])

    def test_a_fix_given_before_the_targets_named_red_was_found_excuses_it(self):
        line = self.line(**{"retry.txt": "\n"})
        self.member(line, {"acme.txt": "red\n"})
        self.land(line)
        self.assertNotIn("excused", line.verdict(1)["fix"])
        line.rig.commit({"retry.txt": None}, "main breaks")
        self.member(line, {"one.txt": "1\n"})
        self.land(line)
        fix = line.verdict(1)["fix"]
        self.assertEqual((fix["tests"], fix["excused"]), (["acme.sh"], ["widget.sh"]))

    def test_a_red_that_named_no_test_holds_the_line_on_the_ladder(self):
        line = self.line(**{"crash.txt": "target breakage\n"})
        self.member(line, {"one.txt": "1\n"})
        self.land(line)
        red, = self.green(line)["red"].values()
        self.assertEqual([key for key in ("tests", "run") if key in red], [], red)
        self.assertEqual([key for key in ("land", "fix") if key in line.verdict(1)], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
