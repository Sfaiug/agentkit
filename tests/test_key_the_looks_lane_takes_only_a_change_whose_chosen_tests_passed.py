"""The looks-alone lane takes only a change whose chosen tests passed.

A change of looks alone lands on its quick checks
(tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py) only where the tests a
reviewer's PASS runs ended green on the commit that review passed, so the project's own tests ran
on it before it goes live.  In a project where a landing on record was red on a test, a reviewed
change of prose alone, its review running that test, lands with no whole suite started, its merge
ending with `Looks-Alone-Tree: <tree>`.  The same change in a project where its review chooses no
test, no landing red on record and no test edited, lands only through the whole suite, its merge
ending with `Suite-Passed-Tree: <tree>`.

Black-box, on the fixtures of that key: the program `AK_BIN` names delivers a run fakeadapter.py
scripts, merged by fakegh.py's GitHub, on a host whose readings are injected (AK_HOST_READINGS):
busy, where a whole suite measured at 40 minutes waits for company, for the change whose tests
were chosen; idle for the other, so the whole suite it waits for runs.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.fakegh import GitHub
import test_key_a_change_of_looks_alone_lands_on_its_quick_checks as quick

# prose outside the project's `content:` only shrinks
NEWS = "Old news.\n"


class TheLooksLaneTakesOnlyAChangeWhoseChosenTestsPassed(unittest.TestCase):
    line = vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)["line"]

    def deliver(self, line, readings):
        """The run that trims news.md, worked and reviewed by scripted harnesses, merged: the
        target's tree and its merge's message."""
        home = line.home
        home.env["AK_HOST_READINGS"] = json.dumps(readings)
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakeadapter.install(home, claude={**fakeadapter.WORK, "write": {"news.md": NEWS},
                                          "commit": "trim the news"}, codex="pass")
        done = home.ak("run", str(taskfile.write(home, line.rig.path, "Trim the news",
                                                 done_when=("test -s news.md",))), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir, = (path for path in taskfile.runs(home) if path.name.endswith("-trim-the-news"))
        self.assertTrue(quick.record(run_dir).get("merged"), quick.record(run_dir))
        tree = line.rig.origin("rev-parse", "main^{tree}")
        return tree, line.rig.origin("log", "-1", "--format=%B", "main").rstrip()

    def test_a_change_whose_chosen_tests_passed_lands_with_no_whole_suite(self):
        line = self.line(**{"news.md": NEWS + "More news.\n"})
        quick.red(line)
        tree, message = self.deliver(line, quick.BUSY)
        # its review ran the test it chose, by name, and nothing ran the whole suite
        self.assertEqual(line.runs(), [("alone", "")])
        self.assertTrue(message.endswith(f"\n\nLooks-Alone-Tree: {tree}"), message)

    def test_where_its_review_chooses_no_test_it_lands_only_through_the_whole_suite(self):
        line = self.line(**{"news.md": NEWS + "More news.\n"})
        tree, message = self.deliver(line, quick.IDLE)
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertNotIn(("alone", ""), line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)


if __name__ == "__main__":
    unittest.main()
