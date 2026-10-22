"""What a turn writes in HOME stays in its box, and what a task's check writes there is thrown away.

A worker runs a model's commands on the owner's machine, where HOME holds the owner's logins,
keys, settings and other checkouts.  A turn changes its workspace and nothing else: a file it
creates in HOME or a dotfile it appends to never reaches the real HOME, executor and reviewer
alike.  A task's checks are boxed as well, yet their writes in HOME succeed, so a check whose
tools keep a cache under ~ still passes; what it wrote is gone once it ends.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from
gitrig.py, with scripted harnesses from fakeadapter.py.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

CHECK = 'echo x > "$HOME/.check-wrote" && echo x >> "$HOME/.gitconfig"'


def writing(step, role, tried):
    """The step, first noting in the adapter's own directory that its turn tried, then
    writing a new file in HOME and appending to a dotfile there."""
    return {**step, "sh": f"echo {role} >> {shlex.quote(str(tried))}; "
                          f'echo x > "$HOME/.{role}-wrote"; echo x >> "$HOME/.gitconfig"'}


class WorkerHomeContained(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.tried = cls.fakes["claude"].dir / "tried"
        cls.fakes["claude"].behave(writing(fakeadapter.WORK, "executor", cls.tried))
        cls.fakes["codex"].behave(writing(fakeadapter.PASS, "reviewer", cls.tried))
        cls.gitconfig = (cls.home.path / ".gitconfig").read_text()
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file",
                              done_when=("test -f retry.txt", CHECK))
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)

    def test_the_run_passes_after_each_turn_tried_to_write_in_home(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        # A pass needs every check to pass, the one writing in HOME among them.
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text())["verdict"], "PASS")
        self.assertEqual(self.tried.read_text().split(), ["executor", "reviewer"])

    def test_no_file_a_turn_or_a_check_creates_in_home_is_in_the_real_home(self):
        for name in (".executor-wrote", ".reviewer-wrote", ".check-wrote"):
            with self.subTest(name):
                self.assertFalse((self.home.path / name).exists())

    def test_a_dotfile_they_append_to_is_unchanged(self):
        self.assertEqual((self.home.path / ".gitconfig").read_text(), self.gitconfig)


if __name__ == "__main__":
    unittest.main()
