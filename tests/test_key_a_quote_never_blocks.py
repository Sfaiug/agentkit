"""A quote never blocks: only a failing command decides what the fixer must answer.

A reviewer's `finding --quote` shows where to look; whether it matters is a test's to say, so
ak weighs it as a note, on an added line as anywhere: the round passes with the note in Notes.
A check line the change removed is proven like any defect: `grep -qF` for it fails while the
line is gone, and that finding blocks.  Black-box through AK_BIN: a real git repository, the
executor's change committed on its branch, and a fake reviewer scripted to hand in, in a run of
one round.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

CHECK = "assert total(-1, 1) == 0"
ADDED = 'print("negatives skipped")'
TESTS = "from api import total\nassert total(2, 2) == 4\n{}\n"


class AQuoteNeverBlocks(unittest.TestCase):
    def review(self, *evidence):
        """One round: the reviewer finds the negative check gone, on the line added in its place;
        the run's record after it."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "acme", files={"api.py": "def total(a, b):\n    return a + b\n",
                                       "tests/test_api.py": TESTS.format(CHECK)})
        akconfig.write(home, ["opus", "astra"])
        # the executor's change: the negative check gives way to a line of its own
        work = {"write": {"tests/test_api.py": TESTS.format(ADDED)}, "commit": "Skip negatives",
                "final": "## Summary\nFixture", "hand_in": [["done"]]}
        review = {"final": "Handed in.", "hand_in": [
            ["finding", "tests/test_api.py:3", "the negative check is gone",
             "negative totals go unchecked", *evidence], ["done"]]}
        fakes = fakeadapter.install(home, claude=work, codex=review)
        task = taskfile.write(home, rig.path, "Skip negatives", done_when=("test -f api.py",),
                              front={"rounds": 1})
        done = home.ak("run", str(task), "--no-merge", timeout=300)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual([(row["argv"][0], row["code"])
                          for row in fakes["codex"].runs()[0]["hand_ins"]],
                         [("finding", 0), ("done", 0)], done.out + done.err)
        return state

    def test_a_quote_on_an_added_line_is_a_note_and_the_round_passes(self):
        state = self.review("--quote", ADDED)
        self.assertEqual([(row["verdict"], row["finding_count"])
                          for row in state["round_summaries"]], [("PASS", 0)])
        self.assertEqual([row["kind"] for row in state["review_records"]], ["note", "done"])
        self.assertEqual(state["followups"], [])
        [note] = state["notes"]
        self.assertIn("tests/test_api.py:3 - the negative check is gone", note)
        self.assertIn(ADDED, note)
        self.assertIn("## Notes\n- tests/test_api.py:3 - the negative check is gone",
                      Path(state["findings_file"]).read_text())

    def test_the_removed_check_line_proven_by_a_command_blocks(self):
        grep = f"grep -qF '{CHECK}' tests/test_api.py"
        state = self.review("--run", grep)
        self.assertEqual([(row["verdict"], row["finding_count"])
                          for row in state["round_summaries"]], [("FAIL", 1)])
        # a review closed with done and holding a finding is a reviewer's FAIL, not one ak overrode
        self.assertEqual([row["kind"] for row in state["review_records"]], ["finding", "done"])
        [row] = [row for row in state["review_records"] if row["kind"] == "finding"]
        self.assertEqual((row["path"], row["line"], row["evidence"]["run"]), ("tests/test_api.py", 3, grep))
        self.assertEqual(state["notes"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
