"""A merge ak finds done after its `gh pr merge` failed says, in the run's log, what the call
answered: its exit code and the last of its output, so whether GitHub, gh or ak failed it shows.

Black-box: the program `AK_BIN` names runs a task to its merge through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py, whose `gh pr merge` merges and
then fails deleting the branch, as when the repository deleted it first.
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

FAILED = ("failed to delete remote branch ak/add-retry-file: HTTP 404: Reference does not exist "
          "(https://api.github.com/repos/acme/widgets/git/refs/heads/ak/add-retry-file)\n")


class MergeFoundDoneSaysWhy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home)
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        cls.gh.reply("pr merge", err=FAILED, code=1, acted=True)
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_log_says_the_call_s_exit_and_output(self):
        warned = [line for line in (self.run_dir / "log.txt").read_text().splitlines()
                  if "WARN" in line and "exited 1" in line]
        self.assertEqual(len(warned), 1, warned)
        self.assertIn(FAILED.strip(), warned[0])

    def test_the_run_still_ends_merged_with_no_revert_line(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertTrue(self.state["merged"], self.state)
        pr = self.gh.pr(1)
        self.assertEqual(pr["state"], "MERGED")
        self.assertNotIn("## How to revert", pr["body"])


if __name__ == "__main__":
    unittest.main()
