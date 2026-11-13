"""A run's folder holding a temporary folder whose maker lives stays through `ak run gc`, however
old the run, a throwaway repo's included; once its maker is gone, the run goes whole.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py; the
temporary folder is one `ak` marks with its maker, here this test's own process.  The collection
is boxed with a /tmp of its own (`home.ak(boxed=True)`), on the host's processes.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home, owner
from fixtures.garbage import ROOM, run

GONE = {"pid": 99999999}


@unittest.skipUnless(boxable(), "no bwrap able to give the collection a /tmp of its own")
class ALivingScratchKeepsItsRun(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def runs(self, maker):
        """An old run and an old throwaway repo's run, each holding a folder `maker` made."""
        throwaway = str(self.home.path / ".agentkit" / "tmp" / "acme-suite")
        for run_id, fields in (("acme-old", {}), ("acme-throwaway", {"repo": throwaway})):
            directory = run(self.home, run_id, 31, state="pass", **fields)
            self.home.write(f".agentkit/runs/{run_id}/tmp-held/.ak-scratch", maker)
            yield directory

    def collect(self):
        done = self.home.ak("run", "gc", boxed=True, env=ROOM)
        self.assertEqual(done.code, 0, done.err)

    def test_a_living_makers_folder_keeps_its_run(self):
        runs = list(self.runs(owner(os.getpid())))
        self.collect()
        self.assertTrue(all((path / "tmp-held").is_dir() for path in runs))
        self.assertTrue(all((path / "run.json").is_file() for path in runs))

    def test_a_gone_makers_folder_keeps_nothing(self):
        runs = list(self.runs(GONE))
        self.collect()
        self.assertFalse(any(path.exists() for path in runs))


if __name__ == "__main__":
    unittest.main()
