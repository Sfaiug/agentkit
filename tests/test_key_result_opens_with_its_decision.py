"""A run needing its seat's decision opens result.md with that decision in full.

Black-box: AK_BIN runs with fakeadapter.py, a temporary HOME and gitrig.py's origin.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

FINDING = "The parser drops the last row of every acme table. " * 20
WHY = "The exported table loses data."
CHECK = "printf 'first diagnostic\\nsecond diagnostic\\n'; false"


class ResultDecision(unittest.TestCase):
    def launch(self, review, *flags):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        gh = GitHub(home)
        gh.grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], settings={"rounds": 1})
        fakeadapter.install(home, claude="work", codex=review)
        task = taskfile.write(home, rig.path, "Add retry file")
        done = home.ak("run", str(task), *flags, timeout=300)
        directory = taskfile.only_run(home)
        return done, json.loads((directory / "run.json").read_text()), (
            directory / "result.md").read_text().splitlines()

    def test_a_failed_review_opens_with_its_whole_decision(self):
        review = {"hand_in": [["finding", "retry.txt:1", FINDING, WHY,
                                "--run", CHECK], ["done"]], "final": "Found one."}
        done, state, lines = self.launch(review, "--rounds", "1", "--no-merge")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertEqual((state["state"], state["rounds"]), ("fail", 1))
        self.assertEqual(lines[0], "# FAIL (1 of 1) — Add retry file")
        self.assertTrue(lines[1].startswith("Why: retry.txt:1 - " + FINDING.strip()), lines[1])
        for text in (WHY, CHECK, "first diagnostic", "second diagnostic"):
            self.assertIn(text, lines[1])
        self.assertGreater(len(lines[1]), 400)
        self.assertEqual(lines[2], "Next: split the task")
        self.assertEqual(lines[3:5], ["", "VERDICT: FAIL"])

    def test_a_merged_pass_keeps_its_heading(self):
        done, state, lines = self.launch("pass")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(state["merged"])
        self.assertEqual(lines[:3], ["# PASS, merged — Add retry file", "", "VERDICT: PASS"])


if __name__ == "__main__":
    unittest.main()
