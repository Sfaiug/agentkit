"""A merged PR's body says how the run's final check went, in the line result.md shows.

The task's `# once` check runs at landing, before ak writes the PR's body and asks GitHub to
merge it, so the body the merged PR holds already carries the run's `final check:` line, among
the records under `---`, ahead of the executor's words.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, against the bare origin of gitrig.py and the
GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
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


class MergedPRBodyFinalCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home)
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path,
                              done_when=("test -f retry.txt", "test -s retry.txt  # once"))
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_merged_pr_carries_the_final_check_line_of_result_md(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertIs(self.state["merged"], True)
        line, = [line for line in (self.run_dir / "result.md").read_text().splitlines()
                 if line.startswith("final check:")]
        self.assertTrue(line.startswith("final check: passed at landing"), line)
        pr, = self.gh.prs()
        self.assertEqual(pr["state"], "MERGED")
        records = pr["body"].split("\n---\n", 1)[1].split("## Executor's summary", 1)[0]
        self.assertIn("- " + line, records.splitlines())


if __name__ == "__main__":
    unittest.main()
