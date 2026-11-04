"""Shared guards on the local default tip do not make different tasks duplicates.

Black-box through AK_BIN: a held fake executor owns a new key, while another task
can run its existing guard. A key on a local branch alone still belongs to the run.
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

GUARD = "tests/test_upload.py"
NEW_KEY = "tests/test_upload_resume.py"
GUARD_CHECKS = ("test -f retry.txt", f"python3 {GUARD}")
CHECKS = (*GUARD_CHECKS, f"test ! -e {NEW_KEY}")


class DuplicateOnlyNewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        # The default is neither main nor the checkout's branch.
        rig.git("checkout", "-q", "-b", "trunk")
        tip = rig.commit({GUARD: "pass\n"}, "add upload guard")
        rig.origin("symbolic-ref", "HEAD", "refs/heads/trunk")
        rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        rig.git("checkout", "-q", "-b", "local-work")
        rig.commit({NEW_KEY: "pass\n"}, "local resume guard", push=False)
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude="work", codex="pass")
        cls.release = fakes["claude"].dir / "release"
        hold = {**fakeadapter.WORK,
                "sh": f"i=0; while [ ! -e {shlex.quote(str(cls.release))} ]"
                      " && [ $i -lt 1500 ]; do sleep 0.2; i=$((i+1)); done"}
        fakes["claude"].behave(hold, "work")
        cls.addClassCleanup(cls.settle)
        first = taskfile.write(home, rig.path, "Resume uploads after interruptions",
                               done_when=CHECKS, name="first")
        launched = home.ak("run", str(first), "--no-merge", "--bg")
        assert launched.code == 0, launched.out + launched.err
        cls.wait(lambda: fakes["claude"].n >= 1)
        cls.first = taskfile.only_run(home)
        cls.existing = cls.launch(taskfile.write(
            home, rig.path, "Improve upload progress labels", done_when=GUARD_CHECKS,
            name="labels"))
        cls.new = cls.launch(taskfile.write(
            home, rig.path, "Resume uploads across reconnects", done_when=CHECKS,
            name="reconnects"))
        # An unreadable tip keeps the old conservative refusal.
        rig.git("update-ref", "-d", "refs/remotes/origin/trunk")
        try:
            cls.unreadable = cls.launch(taskfile.write(
                home, rig.path, "Improve upload keyboard shortcuts", done_when=GUARD_CHECKS,
                name="shortcuts"))
        finally:
            rig.git("update-ref", "refs/remotes/origin/trunk", tip)
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

    @staticmethod
    def state(directory):
        return json.loads((directory / "run.json").read_text())

    @classmethod
    def settle(cls):
        cls.release.touch()
        for directory in taskfile.runs(cls.home):
            cls.wait(lambda: cls.state(directory).get("state") not in ("queued", "running"))

    def refused(self, launched, name):
        done, added = launched
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(added, [], "a refused launch leaves no run")
        self.assertIn(self.first.name, done.err)
        self.assertIn(f"shares {name};", done.err)

    def test_a_shared_guard_on_the_default_tip_starts(self):
        done, added = self.existing
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(len(added), 1, added)
        self.assertEqual(self.state(added[0]).get("verdict"), "PASS")
        self.assertEqual(self.state(self.first).get("verdict"), "PASS")

    def test_a_shared_key_absent_from_the_default_tip_is_refused_and_named(self):
        self.refused(self.new, NEW_KEY)

    def test_an_unreadable_default_tip_counts_every_shared_file(self):
        self.refused(self.unreadable, GUARD)


if __name__ == "__main__":
    unittest.main()
