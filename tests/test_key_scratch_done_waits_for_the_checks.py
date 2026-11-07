"""A scratch run's done waits for the task's checks, as a run in a checkout's does.

A task with `repo: none` has no branch, PR or merge, yet its builder's `ak hand-in done` is
still refused while a done-when command fails in its workspace, so the fix is made in the same
turn.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
with a task from taskfile.py and a scripted harness from fakeadapter.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home

CHECK = "test -f retry.txt"


class ScratchDoneWaitsForTheChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="silent", codex="pass")
        # The first done's answer is kept in the fake's directory, which the turn and the test
        # both see: a file left in the workspace would be delivered.
        cls.said, cls.code = (cls.fakes["claude"].dir / name for name in ("said", "code"))
        said, code = shlex.quote(str(cls.said)), shlex.quote(str(cls.code))
        first = f"{shlex.join([AK, 'hand-in', 'done'])} >{said} 2>&1; echo $? >{code}"
        cls.fakes["claude"].behave({"sh": f"{first}; echo hello >retry.txt",
                                    "hand_in": [["done"]], "final": "## Summary\nwrote retry.txt"})
        task = taskfile.write(cls.home, "none", done_when=(CHECK,))
        cls.done = cls.home.ak("run", str(task), timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_done_is_refused_naming_the_failing_check_then_taken_once_it_passes(self):
        self.assertEqual(self.code.read_text(), "2\n")
        for text in ("done refused: task checks still fail:", CHECK):
            self.assertIn(text, self.said.read_text())
        executor = self.fakes["claude"].runs()
        self.assertEqual([turn["hand_ins"][0]["code"] for turn in executor], [0], executor)

    def test_the_run_then_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state.get("scratch"), self.state.get("state")), (True, "pass"))


if __name__ == "__main__":
    unittest.main()
