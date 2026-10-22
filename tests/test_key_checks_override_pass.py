"""A reviewer's PASS does not land while a done-when check fails: the loop overrides it to FAIL.

The done-when checks are the task's own proof, run by ak on the commit under review, so a
reviewer who hands in no finding cannot outvote them.  The round's verdict is FAIL, the record
says the reviewer's PASS was overridden and why, and with the round budget spent the run ends
FAIL: no branch is pushed, no PR is opened and nothing is merged, though merging was on.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with the GitHub of fakegh.py and scripted harnesses from fakeadapter.py.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# Work committed, handed in done, and never the file the check asks for.
OTHER = {"write": {"other.txt": "hello\n"}, "commit": "add other.txt",
         "final": "## Summary\nwrote other.txt", "hand_in": [["done"]]}
OVERRIDDEN = "the reviewer said PASS while done-when is failing"


class ChecksOverridePass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.base = cls.rig.head()
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")      # a PASS could be pushed and merged
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=OTHER, codex="pass")
        # one round, so the overridden review is the run's last word
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file", front={"rounds": 1})
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_reviewer_handed_in_pass_and_the_round_is_failed_instead(self):
        turns = [(run["role"], [(hand["argv"], hand["code"]) for hand in run["hand_ins"]])
                 for run in self.fakes["codex"].runs()]
        self.assertEqual(turns, [("reviewer", [(["done"], 0)])])
        log = [re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line)
               for line in (self.run_dir / "log.txt").read_text().splitlines()]
        warned = log.index(f"WARN {OVERRIDDEN}; overriding to FAIL")
        self.assertEqual(log[warned + 1], "round 1 verdict: FAIL")
        self.assertEqual([(summary["verdict"], summary["done_when"])
                          for summary in self.state["round_summaries"]], [("FAIL", False)])
        self.assertEqual({key: self.state["review"].get(key) for key in (
            "verdict", "done_when", "overridden")}, {
            "verdict": "FAIL", "done_when": False, "overridden": OVERRIDDEN})
        checks = (self.run_dir / "round-1/donewhen.log").read_text()
        self.assertIn("$ test -f retry.txt\n[exit 1]", checks)

    def test_the_run_ends_fail_and_nothing_lands(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertTrue(self.done.out.rstrip("\n").endswith(
            f"FAIL -> {self.run_dir / 'result.md'}"), self.done.out)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "merged", "pr")}, {
            "state": "fail", "verdict": "FAIL", "merged": False, "pr": None})
        self.assertFalse([call for call in self.home.calls("gh")
                          if call[:2] in (["pr", "create"], ["pr", "merge"])])
        self.assertEqual(self.gh.prs(), [])
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.rig.head(), self.base)

    def test_result_md_says_fail_and_why_the_reviewer_s_pass_was_overridden(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# FAIL — Add retry file")
        for line in ("VERDICT: FAIL", "rounds: 1 of 1", "pr: (none)", "merged: no",
                     "## Round 1 (FAIL, done-when failed)"):
            self.assertIn(line, lines)
        overridden = lines.index("## Overridden to FAIL")
        self.assertEqual(lines[overridden + 1], OVERRIDDEN)
        # the check the reviewer's PASS ran into, as the task named it
        checks = lines.index("## Done-when")
        self.assertEqual(lines[checks + 1:checks + 4], ["```", "test -f retry.txt", "```"])


if __name__ == "__main__":
    unittest.main()
