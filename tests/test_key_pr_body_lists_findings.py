"""A merged PR's body lists, under `## Findings`, each `findings` row its run has in history.db.

One line per row in round order: the round, `path:line`, the kind handed in, the kind ak weighed
it as where that differs, and how the row ended: a dispute by its outcome, ak's replay of an
earlier finding by its word.  A run with no row has no such section.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, against the bare origin of
gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# Each fails while its line of words.txt is lower case, and passes on base, which has no file.
FIRST = "! grep -qx first words.txt"
SECOND = "! grep -qx second words.txt"
WORK = {"write": {"retry.txt": "hello\n", "words.txt": "first\nsecond\n"},
        "commit": "add retry.txt and words.txt", "final": "## Summary\nwrote both",
        "hand_in": [["done"]]}
REVIEW = {"final": "Found two.", "hand_in": [
    ["finding", "words.txt:1", "the first line is lower case", "it opens the file", "--run", FIRST],
    ["finding", "words.txt:2", "the second line is lower case", "it reads as one", "--run", SECOND],
    ["done"]]}
# fixes the first finding and disputes the second, which the next review concedes and passes
FIX = {"write": {"words.txt": "First\nsecond\n"}, "commit": "capitalise the first line",
       "final": "## Summary\ncapitalised the first line", "hand_in": [
           ["dispute", "words.txt:2", "lower case is the house style", "--run", "true"], ["done"]]}
CONCEDE = {"final": "Agreed.", "hand_in": [
    ["concede", "words.txt:2", "Lower case is allowed."], ["done"]]}
OTHER = {"write": {"other.txt": "hello\n"}, "commit": "add other.txt",
         "final": "## Summary\nwrote other.txt", "hand_in": [["done"]]}
FINDINGS = ["- round 1 `words.txt:1` finding",
            "- round 1 `words.txt:2` finding",
            "- round 2 `words.txt:1` finding, weighed as note: fixed; its proof passes now",
            "- round 2 `words.txt:2` dispute: conceded"]
# The Home's notify sink marks every run a test suite's, which history.db never records: these
# runs go without it, and with no webhook configured nothing is posted anywhere.
OWNERS = {"AK_NOTIFY_SINK": None}


class PRBodyListsFindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home)
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        fakes = fakeadapter.install(cls.home, claude=[WORK, FIX], codex=[REVIEW, CONCEDE])
        cls.found = cls.home.ak("run", str(taskfile.write(cls.home, cls.rig.path, "Add words")),
                                env=OWNERS, timeout=300)
        fakes["claude"].behave(OTHER)
        fakes["codex"].behave("pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add other", done_when=("test -f other.txt",))
        cls.clean = cls.home.ak("run", str(task), env=OWNERS, timeout=300)

    def merged_body(self, done, index):
        self.assertEqual(done.code, 0, done.out + done.err)
        prs = self.gh.prs()
        self.assertEqual(len(prs), 2, prs)
        self.assertEqual(prs[index]["state"], "MERGED", prs[index])
        return prs[index]["body"]

    def test_each_row_is_a_line_in_round_order_with_how_it_ended(self):
        body = self.merged_body(self.found, 0)
        self.assertIn("\n## Findings\n\n" + "\n".join(FINDINGS) + "\n\n", body)

    def test_the_findings_stand_before_the_records_that_can_fill_the_limit(self):
        body = self.merged_body(self.found, 0)
        self.assertLess(body.index("- run:"), body.index("## Findings\n"))
        self.assertLess(body.index("## Findings\n"), body.index("## Notes\n"))
        self.assertLess(body.index("## Notes\n"), body.index("## Executor's summary\n"))

    def test_a_run_whose_review_found_nothing_has_no_findings_section(self):
        body = self.merged_body(self.clean, 1)
        self.assertNotIn("## Findings", body)
        self.assertIn("## Executor's summary\n", body)


if __name__ == "__main__":
    unittest.main()
