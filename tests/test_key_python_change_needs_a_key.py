"""Where a repository's base holds an answer key (tests/test_key_*.py), a change that writes a .py
file outside tests/ brings a key with it, else its round fails naming those files, though the
task's checks and the reviewer passed.

A key counts when the change adds or edits one, or renames a test into one.  A Python file deleted
or moved unchanged needs none, nor does a change to tests/ alone, and a base holding no key is out
of the rule.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, with scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PLAIN = {"src/widget.py": "def turns():\n    return 1\n", "src/spare.py": "SPARE = 1\n",
         "tests/test_widget.py": "from widget import turns\nassert turns() == 1\n"}
KEYED = {**PLAIN, "tests/test_key_widget_starts.py": "# starts the widget from outside\n"}
# The widget edited, and its plain test with it.
EDIT = {"src/widget.py": "def turns():\n    return 2\n",
        "tests/test_widget.py": "from widget import turns\nassert turns() == 2\n"}
REFUSAL = ("Python changed with no answer key: src/widget.py. A change to a .py file outside "
           "tests/ adds, edits or moves in a tests/test_key_*.py in the same change: a black-box "
           "test of what it does.")


def step(write, sh=None):
    """A worker turn that writes `write`, runs `sh`, commits all of it and hands in done."""
    return {"write": write, **({"sh": sh} if sh else {}), "commit": "change widgets",
            "final": "## Summary\nchanged widgets", "hand_in": [["done"]]}


def refusals(text):
    return [line for line in text.splitlines() if line.startswith("Python changed")]


class RunOn:
    """One run of a one-round task on a base holding `files`, whose check `done_when` proves the
    change was made, with a passing reviewer; its record read once it has ended."""

    @classmethod
    def start(cls, files, done_when, *steps):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets", files=files)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=list(steps), codex="pass")
        task = taskfile.write(cls.home, rig.path, "Change widgets", front={"rounds": 1},
                              done_when=(done_when,))
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def assert_passed(self, *roles):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([(entry["verdict"], entry["done_when"])
                          for entry in self.state["round_summaries"]], [("PASS", True)])
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()], list(roles))
        self.assertEqual(refusals((self.run_dir / "round-1/donewhen.log").read_text()), [])


class PythonEditedBesideAPlainTest(RunOn, unittest.TestCase):
    """The executor edits the widget and its plain test, and deletes the base's key, which frees
    nothing; the fixer the refusal gets adds a key."""

    @classmethod
    def setUpClass(cls):
        cls.start(KEYED, "grep -q 2 src/widget.py",
                  step(EDIT, "git rm -q tests/test_key_widget_starts.py"),
                  step({"tests/test_key_widget_turns.py": "# turns the widget from outside\n"}))

    def test_the_round_fails_naming_the_python_file_and_not_its_test(self):
        prompt = (self.run_dir / "round-1/fixer/prompt.md").read_text()
        failed = prompt.split("## The done-when commands failed.", 1)
        self.assertEqual(len(failed), 2, prompt)
        self.assertIn("$ grep -q 2 src/widget.py\n[exit 0]", failed[1])
        self.assertEqual(refusals(failed[1]), [REFUSAL])

    def test_a_new_key_passes_it(self):
        self.assert_passed("executor", "fixer")


class PlainTestRenamedToAKey(RunOn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start(KEYED, "test -f tests/test_key_widget.py",
                  step({"src/widget.py": EDIT["src/widget.py"]},
                       "git mv tests/test_widget.py tests/test_key_widget.py"))

    def test_the_round_passes(self):
        self.assert_passed("executor")


class PythonMovedOrDeletedBesideTests(RunOn, unittest.TestCase):
    """One Python file moved unchanged, another deleted, and a plain test edited, which the first
    class shows gives no key: none of them needs one."""

    @classmethod
    def setUpClass(cls):
        cls.start(KEYED, "test -f src/gadget.py && test ! -e src/spare.py",
                  step({"tests/test_widget.py": EDIT["tests/test_widget.py"]},
                       "git mv src/widget.py src/gadget.py && git rm -q src/spare.py"))

    def test_the_round_passes(self):
        self.assert_passed("executor")


class BaseWithoutKeys(RunOn, unittest.TestCase):
    """The first class's change, on a base that holds no key."""

    @classmethod
    def setUpClass(cls):
        cls.start(PLAIN, "grep -q 2 src/widget.py", step(EDIT))

    def test_the_round_passes(self):
        self.assert_passed("executor")


if __name__ == "__main__":
    unittest.main()
