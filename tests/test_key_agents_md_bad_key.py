"""A branch that changes AGENTS.md into rules workers would not get as written fails its round.

ak reads AGENTS.md's front matter itself, and only six names in it (tests, health, cleanup,
users, features, suite_image), so a line it does not read is a misspelling that silently drops
a rule, and a link is a file no worker's prompt gets.  A run whose work does either fails its
checks even when the reviewer passes it, the fixer is told which line to remove, and nothing is
delivered.  What judges this is the branch's change: a line the base already holds is the
owner's, and a run that leaves AGENTS.md alone passes over it.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, against
the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# Read names and a comment around the one ak does not read.
UNREAD = "---\nusers: none\ntset: x\n# a note for people\n---\n# widgets\n"


def work(**extra):
    """The executor's turn: the task's file, and whatever else the step adds."""
    step = {**fakeadapter.WORK, **extra}
    step["write"] = {**fakeadapter.WORK["write"], **extra.get("write", {})}
    return step


class RunOn:
    """One run of the task in a Home of its own, its record read once it has ended."""

    @classmethod
    def start(cls, step, *args, files=None, gh=False):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files=files)
        cls.base = cls.rig.head()
        if gh:
            cls.gh = GitHub(cls.home)
            cls.gh.grant(cls.rig.slug, "WRITE")    # enough that a pass would merge
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=step, codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, front={"rounds": 1})
        cls.done = cls.home.ak("run", str(task), *args, timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.checks = (cls.run_dir / "round-1/donewhen.log").read_text()

    def assert_failed_though_the_reviewer_passed(self):
        self.assertNotEqual(self.done.code, 0, self.done.out)
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "merged")},
                         {"state": "fail", "verdict": "FAIL", "merged": False})
        self.assertEqual([(entry["verdict"], entry["done_when"])
                          for entry in self.state["round_summaries"]], [("FAIL", False)])
        reviews = self.fakes["codex"].runs()
        self.assertEqual([(run["role"], run["hand_ins"][-1]["argv"]) for run in reviews],
                         [("reviewer", ["done"])])
        # the task's own check passed: the refusal is the whole failure
        self.assertIn("$ test -f retry.txt\n[exit 0]", self.checks)

    def refusal(self, *words):
        """The one line of the checks' output naming AGENTS.md and every word."""
        found = [line for line in self.checks.splitlines()
                 if "AGENTS.md" in line and all(word in line for word in words)]
        self.assertEqual(len(found), 1, self.checks)
        return found[0]


class BranchAddsAnUnreadLine(RunOn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start(work(write={"AGENTS.md": UNREAD}), gh=True)

    def test_the_round_fails_though_the_reviewer_passed_it(self):
        self.assert_failed_though_the_reviewer_passed()

    def test_the_checks_name_the_unread_line_and_only_it(self):
        line = self.refusal("`tset: x`")
        self.assertNotIn("users: none", line)
        self.assertNotIn("a note for people", line)

    def test_the_fixer_is_told_which_line_to_remove(self):
        turns = self.fakes["claude"].runs()
        self.assertEqual([turn["role"] for turn in turns], ["executor", "fixer"])
        self.assertIn("`tset: x`", Path(turns[1]["argv"][3]).read_text())

    def test_result_md_says_fail_and_why(self):
        text = (self.run_dir / "result.md").read_text()
        lines = text.splitlines()
        self.assertEqual(lines[4], "# FAIL — Add retry file")
        for line in ("VERDICT: FAIL", "rounds: 1 of 1", "pr: (none)", "merged: no"):
            self.assertIn(line, lines)
        self.assertIn("`tset: x`", text)

    def test_nothing_is_pushed_opened_or_merged(self):
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.rig.head(), self.base)
        self.assertEqual(self.gh.prs(), [])
        self.assertIsNone(self.state.get("pr"))


class BranchMakesItALink(RunOn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start(work(sh="ln -s RULES.md AGENTS.md"), "--no-merge",
                  files={"RULES.md": "---\nusers: none\n---\n# widgets\n"})

    def test_the_round_fails_naming_the_link(self):
        self.assert_failed_though_the_reviewer_passed()
        self.refusal("link")


class BaseAlreadyHoldsAnUnreadLine(RunOn, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start("work", "--no-merge", files={"AGENTS.md": "---\ncolour: red\n---\n# w\n"})

    def test_a_run_that_leaves_agents_md_alone_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict")},
                         {"state": "pass", "verdict": "PASS"})
        self.assertEqual([(entry["verdict"], entry["done_when"])
                          for entry in self.state["round_summaries"]], [("PASS", True)])
        self.assertNotIn("colour: red", self.checks)
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()], ["executor"])


if __name__ == "__main__":
    unittest.main()
