"""A follow-up's text begins with its file's whole name, leading spaces too.

ak takes a review's site at any file inside the checkout, ` api.py` beside `api.py`; the text
of a follow-up begins with that name as given, every character of it.  So the same defect
handed in at each of three such files is three follow-ups in run.json, each with its own check,
none taken for another.  Black-box: the program `AK_BIN` names runs from outside through
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

FILES = ("api.py", " api.py", "  api.py")


class AFollowUpNamesItsWholeFile(unittest.TestCase):
    def test_the_same_defect_in_each_file_is_its_own_follow_up(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={name: "old\n" for name in FILES})
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex={"final": "One defect, in three files.",
            "hand_in": [*(["follow-up", f"{name}:1", "old data", "callers break", "--run", "false"]
                          for name in FILES), ["done"]]})
        task = taskfile.write(home, rig.path, "Add retry file")
        done = home.ak("run", str(task), "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual([item.splitlines()[0] for item in state["followups"]],
                         [f"{name}:1 - old data - callers break" for name in FILES])
        self.assertEqual(state["followup_checks"], {item: "false" for item in state["followups"]})


if __name__ == "__main__":
    unittest.main()
