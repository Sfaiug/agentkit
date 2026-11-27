"""A run launched with `--no-merge` whose task lists the project's `tests:` suite, here by its
bare first command, is refused at launch and the suite does not run: it runs once, at landing.
Black-box: `AK_BIN` (tests/fixtures/akbin.py) on a gitrig.py project with scripted harnesses.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

BARE = "sh suite.sh"
FILES = {"AGENTS.md": f"---\ntests: {BARE} 2>&1 | tee suite.out\nhealth: none\nusers: none\n---\n",
         "suite.sh": 'echo ran >>"$(git rev-parse --git-common-dir)/suite.log"\n'}


class ARunThatDoesNotLandRunsNoSuite(unittest.TestCase):
    def test_a_task_listing_the_suite_is_refused_and_the_suite_never_runs(self):
        with Home() as home:
            rig = Rig(home, "widgets", files=FILES)
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")
            task = taskfile.write(home, rig.path, done_when=("test -f retry.txt", BARE))
            done = home.ak("run", str(task), "--no-merge", timeout=300)
            self.assertEqual(done.code, 2, done.out + done.err)
            self.assertIn(f"done-when line `{BARE}` is widgets's whole-suite `tests:` command",
                          done.err)
            self.assertFalse((rig.path / ".git" / "suite.log").exists())


if __name__ == "__main__":
    unittest.main()
