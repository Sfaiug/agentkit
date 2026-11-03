"""A live run owns its source task file, not words shared by a different task's title.

Black-box: AK_BIN runs in a throwaway Home with a held fake executor, just as in
test_key_run_duplicates.py. Changing the source's title and checks cannot hide its identity.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

TITLE = "Keep upload retries working across mobile connections"
OTHER_TITLE = "Keep upload retries working across desktop sessions"


class DuplicateByTaskFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        cls.release = fakes["claude"].dir / "release"
        hold = {**fakeadapter.WORK,
                "sh": f"i=0; while [ ! -e {shlex.quote(str(cls.release))} ]"
                      " && [ $i -lt 1500 ]; do sleep 0.2; i=$((i+1)); done"}
        fakes["claude"].behave(hold, "work")
        cls.task = taskfile.write(home, rig.path, TITLE, name="mobile",
                                  done_when=("test -f retry.txt", "test ! -e tests/test_mobile.py"))
        cls.addClassCleanup(cls.settle)
        launched = home.ak("run", str(cls.task), "--no-merge", "--bg")
        assert launched.code == 0, launched.out + launched.err
        cls.wait(lambda: fakes["claude"].n >= 1)
        cls.first = taskfile.only_run(home)
        # The running run holds its own copy; its source may change before a relaunch.
        taskfile.write(home, rig.path, "Tidy widget colours", name="mobile",
                       done_when=("test -f retry.txt", "test ! -e tests/test_colours.py"))
        cls.same = cls.launch(cls.task)
        other = taskfile.write(home, rig.path, OTHER_TITLE, name="desktop",
                               done_when=("test -f retry.txt", "test ! -e tests/test_desktop.py"))
        cls.other = cls.launch(other)
        cls.settle()

    @classmethod
    def launch(cls, task):
        before = set(taskfile.runs(cls.home))
        done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        return done, sorted(set(taskfile.runs(cls.home)) - before)

    @staticmethod
    def wait(ready):
        deadline = time.monotonic() + 120
        while not ready():
            assert time.monotonic() < deadline, "the held run did not start or end"
            time.sleep(0.2)

    @classmethod
    def settle(cls):
        cls.release.touch()
        for directory in taskfile.runs(cls.home):
            cls.wait(lambda: json.loads((directory / "run.json").read_text()).get("state")
                     not in ("queued", "running"))

    def test_the_same_task_file_is_refused_and_names_the_live_run(self):
        done, added = self.same
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(added, [])
        self.assertIn(self.first.name, done.err)
        self.assertIn(TITLE, done.err)
        self.assertIn(f"shares task file {self.task.resolve()};", done.err)

    def test_a_different_task_sharing_five_title_words_and_no_test_starts(self):
        done, added = self.other
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(len(added), 1, added)
        state = json.loads((added[0] / "run.json").read_text())
        self.assertEqual(state.get("verdict"), "PASS")


if __name__ == "__main__":
    unittest.main()
