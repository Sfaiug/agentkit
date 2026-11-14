"""A PR ak squash-merged says, last in its description, the command that reverts the merge.

Black-box: the program `AK_BIN` names runs a task to its merge through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py.  The executor's summary is
longer than a PR description may be, so the description ak opened is already cut, and the
section added after the merge must cut it again rather than be cut itself.
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


SUMMARY = "## Summary\n" + "Wrote retry.txt. " * 5000
GITHUB_LIMIT = 65_536


class MergedPRSaysHowToRevert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home)
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude={**fakeadapter.WORK, "final": SUMMARY}, codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_merged_description_ends_with_the_revert_of_the_squash_commit(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        pr = self.gh.pr(1)
        self.assertEqual((pr["state"], pr["merge"]["method"]), ("MERGED", "squash"))
        self.assertEqual(self.rig.head(), pr["merge"]["commit"])
        section = f"\n\n## How to revert\n\n```bash\ngit revert {pr['merge']['commit']}\n```\n"
        self.assertTrue(pr["body"].endswith(section), pr["body"][-400:])
        self.assertEqual(pr["body"].count("## How to revert"), 1)

    def test_the_description_ak_opened_stays_ahead_of_it_cut_to_github_s_limit(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        body, opened = self.gh.pr(1)["body"], (self.run_dir / "pr-body.md").read_text()
        self.assertGreater(len(SUMMARY), GITHUB_LIMIT)
        self.assertTrue(body.startswith(opened[:opened.index("## Executor's summary\n")]), body)
        self.assertIn("## Executor's summary\n\n## Summary\nWrote retry.txt.", body)
        self.assertLessEqual(len(body.encode("utf-8")), GITHUB_LIMIT)


if __name__ == "__main__":
    unittest.main()
