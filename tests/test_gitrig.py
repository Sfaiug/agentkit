"""The answer key's project is a clone and its bare origin, entirely on disk.

A run test judges what ak pushed and landed by reading the origin, and what it only branched
by reading the clone; both hold only if tests/fixtures/gitrig.py keeps the two apart as a
project and its GitHub remote are.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


class Project(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "widgets", files={"AGENTS.md": "# widgets\n"})

    def test_the_clone_tracks_a_bare_origin_holding_one_init_commit(self):
        rig = self.rig
        self.assertEqual((rig.path, rig.slug), (self.home.path / "code/widgets", "acme/widgets"))
        self.assertEqual(rig.origin("rev-parse", "--is-bare-repository"), "true")
        self.assertEqual(rig.git("remote", "get-url", "origin"), str(rig.bare))
        self.assertEqual(rig.git("rev-parse", "--abbrev-ref", "@{upstream}"), "origin/main")
        self.assertEqual(rig.origin("log", "--format=%s %an <%ae>"),
                         "init acme <acme@example.com>")
        self.assertEqual(rig.files(), [".keep", "AGENTS.md"])

    def test_a_commit_reaches_the_origin_unless_kept_local(self):
        pushed = self.rig.commit({"api/v1.py": "x = 1\n"}, "add api")
        self.assertEqual(self.rig.head(), pushed)
        local = self.rig.commit({"api/v1.py": "x = 2\n"}, push=False)
        self.assertEqual((self.rig.head(), self.rig.head(remote=False)), (pushed, local))
        self.assertIn("api/v1.py", self.rig.files("main"))

    def test_a_branch_is_cut_from_main_and_the_clone_stays_on_main(self):
        pushed = self.rig.branch("fix-api", {"api.py": "x = 2\n"})
        self.rig.branch("beta", push=False)
        self.assertEqual(self.rig.git("branch", "--show-current"), "main")
        self.assertEqual(self.rig.branches(), ["fix-api", "main"])
        self.assertEqual(self.rig.branches(remote=False), ["beta", "fix-api", "main"])
        self.assertEqual(self.rig.head("fix-api"), pushed)
        self.assertEqual(self.rig.files("fix-api"), [".keep", "AGENTS.md", "api.py"])
        self.assertIsNone(self.rig.head("nosuch"))

    def test_ak_cuts_a_run_from_what_the_origin_holds(self):
        pushed = self.rig.commit({"api.py": "x = 1\n"})
        self.rig.commit({"api.py": "x = 2\n"}, push=False)
        # No harness is installed: the run ends unstaffed, after its base is chosen.
        self.home.ak("run", str(taskfile.write(self.home, self.rig.path)), "--no-merge")
        run = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual(run["base_sha"], pushed)


if __name__ == "__main__":
    unittest.main()
