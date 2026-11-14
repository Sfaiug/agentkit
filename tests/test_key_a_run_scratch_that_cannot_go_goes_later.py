"""A dead maker's scratch whose run's folder is closed to writing stays, its mark kept, and
goes at the first `ak run gc` after that folder opens again.

Black-box: `AK_BIN` collects a Home (tests/fixtures/akbin.py) holding the scratch the way ak
leaves it, its mark naming a process long gone, with a /tmp of its own (`home.ak(boxed=True)`):
once with the run's folder at mode 0500, once at 0700.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.garbage import ROOM, run


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class ARunScratchThatCannotGoGoesLater(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(Home())
        self.folder = run(self.home, "acme-held", 1, state="pass")
        self.mark = self.home.write(".agentkit/runs/acme-held/tmp-left/.ak-scratch",
                                    {"pid": 99999999, "process_identity": None})
        self.scratch = self.mark.parent
        (self.scratch / "payload").write_text("scratch\n")
        self.folder.chmod(0o500)
        self.addCleanup(self.folder.chmod, 0o700)

    def test_it_keeps_its_mark_and_goes_once_its_run_s_folder_opens(self):
        done = self.home.ak("run", "gc", boxed=True, env=ROOM)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(f"gc: kept {self.scratch}", done.out)
        self.assertEqual([path.name for path in self.scratch.iterdir()], [".ak-scratch"])

        self.folder.chmod(0o700)
        done = self.home.ak("run", "gc", boxed=True, env=ROOM)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(f"gc: remove run-scratch {self.scratch}", done.out)
        self.assertFalse(self.scratch.exists())
        self.assertTrue((self.folder / "run.json").is_file())


if __name__ == "__main__":
    unittest.main()
