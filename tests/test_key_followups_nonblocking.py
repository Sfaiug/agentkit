"""A reviewer's follow-up is kept with its proof and check, and never holds a run back.

A follow-up is a defect the review found that the task did not cause: it is the reviewer's way
to say "this is wrong too" without holding the work back.  So a review that hands in only a
follow-up and `done` passes in that round, with no work sent back; run.json keeps the item,
its proof on the reviewed commit and on the base, and its `--run` command as the check that
will say when it is fixed; and result.md lists it under its own Follow-ups heading, not as a
finding.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, a config from akconfig.py, a task from
taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

ITEM = "retry.txt:1 - old defect - it matters later"
FOLLOW_UP = {"final": "One defect from before the task.", "hand_in": [
    ["follow-up", "retry.txt:1", "old defect", "it matters later", "--run", "false"],
    ["done"]]}


class FollowUpsNeverBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        cls.base = rig.head()
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex=FOLLOW_UP)
        task = taskfile.write(cls.home, rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_a_review_with_only_a_follow_up_passes_in_its_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        hand_ins = self.fakes["codex"].runs()[0]["hand_ins"]
        self.assertEqual([(row["argv"][0], row["code"]) for row in hand_ins],
                         [("follow-up", 0), ("done", 0)])
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([(summary["verdict"], summary["finding_count"])
                          for summary in self.state["round_summaries"]], [("PASS", 0)])
        # no fixer turn and no second review: the follow-up held nothing back
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))

    def test_run_json_keeps_the_item_its_proof_and_its_command_as_the_check(self):
        followups = self.state["followups"]
        self.assertEqual(len(followups), 1, followups)
        lines = followups[0].splitlines()
        self.assertEqual(lines[:2], [ITEM, "$ false"])
        # proven on the commit reviewed and on the base the task started from
        self.assertIn(self.state["review"]["head_sha"], followups[0])
        self.assertIn(self.base, followups[0])
        self.assertEqual(self.state["followup_checks"], {followups[0]: "false"})

    def test_it_is_no_finding(self):
        findings = self.run_dir / "round-1/reviewer/findings.json"
        self.assertEqual(json.loads(findings.read_text()), [])

    def test_result_md_lists_it_under_its_own_follow_ups_heading(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertIn("VERDICT: PASS", lines)
        self.assertEqual(lines.count("## Follow-ups"), 1, lines)
        listed = lines[lines.index("## Follow-ups") + 1:]
        self.assertEqual(next(line for line in listed if line.strip()), f"- {ITEM}")


if __name__ == "__main__":
    unittest.main()
