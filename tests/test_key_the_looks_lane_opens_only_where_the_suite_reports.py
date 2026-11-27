"""The looks-alone lane opens only where the suite reports its tests to ak.

A target that declares both `health:` and `deployed:` lets a change of looks alone land on its
quick checks (tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py) only where the
project has a time record of its suite.  With no record (or an empty one), a change of an image
waits on a busy host like any member and lands through the whole suite, its merge ending with
`Suite-Passed-Tree: <tree>`; with a time record it lands as looks alone, with no whole run and
`Looks-Alone-Tree: <tree>`.

Black-box, on the fixtures of tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py:
the program `AK_BIN` names, through tests/fixtures/akline.py, fakeadapter.py and fakegh.py's
GitHub, with injected host readings (AK_HOST_READINGS).
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.fakegh import GitHub
import test_key_a_change_of_looks_alone_lands_on_its_quick_checks as quick


class TheLooksLaneOpensOnlyWhereTheSuiteReports(unittest.TestCase):
    line, join, land, checked = (vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)[name]
                                 for name in ("line", "join", "land", "checked"))

    def deliver(self, line, readings):
        home = line.home
        home.env["AK_HOST_READINGS"] = json.dumps(readings)
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakeadapter.install(home, claude={**fakeadapter.WORK, "write": quick.IMAGE,
                                          "commit": "draw"}, codex="pass")
        done = home.ak("run", str(taskfile.write(home, line.rig.path, "Draw the logo",
                                                 done_when=("test -f logo.png",))), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir, = (path for path in taskfile.runs(home) if path.name.endswith("-draw-the-logo"))
        self.assertTrue(quick.record(run_dir).get("merged"), quick.record(run_dir))
        tree = line.rig.origin("rev-parse", "main^{tree}")
        return tree, line.rig.origin("log", "-1", "--format=%B", "main").rstrip()

    def test_with_no_time_record_an_image_lands_through_the_whole_suite(self):
        line = self.line(times=None)
        tree, message = self.deliver(line, quick.IDLE)
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)

    def test_with_no_time_record_an_image_waits_on_a_busy_host(self):
        for times in (None, {}):
            with self.subTest(times=times):
                line = self.line(times=times)
                self.join(line, quick.IMAGE)
                self.land(line, quick.BUSY)
                self.assertEqual(self.checked(line), (0, [False]), line.runs())

    def test_with_a_time_record_an_image_lands_as_looks_alone(self):
        line = self.line()
        tree, message = self.deliver(line, quick.BUSY)
        self.assertEqual(line.whole(), 0, line.runs())
        self.assertTrue(message.endswith(f"\n\nLooks-Alone-Tree: {tree}"), message)


if __name__ == "__main__":
    unittest.main()
