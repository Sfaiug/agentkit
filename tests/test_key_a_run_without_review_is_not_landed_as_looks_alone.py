"""A run that took no review is not landed as looks alone.

A target that declares `health:` and `deployed:` and has a time record of its suite lets a change
of looks alone land on its quick checks
(tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py) only when a reviewer gave
its PASS.  A run whose recorded review says `no_review` -- because its change touched only paths
the target marks `ak-checks-only`, or because review is off -- ran none of the tests a reviewer's
PASS runs, so it waits on a busy host and lands through the whole suite, its merge carrying no
`Looks-Alone-Tree` trailer (`Suite-Passed-Tree: <tree>`).  The same change on a target without the
mark, reviewed, lands as looks alone with no whole run and `Looks-Alone-Tree: <tree>`.

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


class ARunWithoutReviewIsNotLandedAsLooksAlone(unittest.TestCase):
    line, join, land, checked = (vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)[name]
                                 for name in ("line", "join", "land", "checked"))

    def deliver(self, line, readings, *, settings=None):
        home = line.home
        home.env["AK_HOST_READINGS"] = json.dumps(readings)
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       settings=settings)
        fakes = fakeadapter.install(home, claude={**fakeadapter.WORK, "write": quick.STYLE,
                                                  "commit": "restyle"}, codex="pass")
        done = home.ak("run", str(taskfile.write(home, line.rig.path, "Restyle the site",
                                                 done_when=("test -f site.css",))), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir, = (path for path in taskfile.runs(home) if path.name.endswith("-restyle-the-site"))
        self.assertTrue(quick.record(run_dir).get("merged"), quick.record(run_dir))
        tree = line.rig.origin("rev-parse", "main^{tree}")
        return fakes["codex"].n, tree, line.rig.origin("log", "-1", "--format=%B", "main").rstrip()

    def test_marked_stylesheets_land_through_the_whole_suite(self):
        line = self.line(**{".gitattributes": "*.css ak-checks-only\n"})
        reviews, tree, message = self.deliver(line, quick.IDLE)
        self.assertEqual(reviews, 0)
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)
        self.assertNotIn("Looks-Alone-Tree", message)

    def test_review_off_stylesheet_lands_through_the_whole_suite(self):
        line = self.line()
        reviews, tree, message = self.deliver(line, quick.IDLE, settings={"review_rounds": 0})
        self.assertEqual(reviews, 0)
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)
        self.assertNotIn("Looks-Alone-Tree", message)

    def test_an_unreviewed_stylesheet_waits_on_a_busy_host_while_a_reviewed_one_lands(self):
        line = self.line()
        self.join(line, quick.STYLE)
        state = quick.record(line.members[0])
        state["review"]["no_review"] = True
        (line.members[0] / "run.json").write_text(json.dumps(state))
        self.join(line, quick.STYLE)
        self.land(line, quick.BUSY)
        self.assertEqual(self.checked(line), (0, [False, True]), line.runs())

    def test_without_the_mark_a_reviewed_stylesheet_lands_as_looks_alone(self):
        line = self.line()
        reviews, tree, message = self.deliver(line, quick.BUSY)
        self.assertEqual(reviews, 1)
        self.assertEqual(line.whole(), 0, line.runs())
        self.assertTrue(message.endswith(f"\n\nLooks-Alone-Tree: {tree}"), message)


if __name__ == "__main__":
    unittest.main()
