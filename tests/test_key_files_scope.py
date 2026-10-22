"""A task's `files:` lines bound what its branch may change: a path outside them fails the round.

`files:` holds Git pathspecs, comma-separated and repeatable.  After each round's checks ak
compares the branch's changed paths with them, and any path none matches fails the gate with
`outside files: <paths>`, whatever the checks and the reviewer said: the fixer is shown that
line, a reviewer's PASS is overridden to FAIL, and the work does not land.  Paths inside the
pathspecs pass as if there were no limit.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, on a project from gitrig.py with the GitHub of
fakegh.py, and scripted harnesses from fakeadapter.py.
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

SPECS = ["src/, docs/", "lib/c.txt"]


def wrote(*paths):
    """An executor turn that writes and commits each path, then hands in done."""
    return {"write": {path: f"{path}\n" for path in paths}, "commit": "add files",
            "final": "## Summary\nwrote files", "hand_in": [["done"]]}


def launch(home, rig, claude, front, *args, **task):
    """Run the task with the executor scripted and a passing reviewer; what ak left."""
    akconfig.write(home, ["opus", "astra"])
    fakes = fakeadapter.install(home, claude=claude, codex="pass")
    path = taskfile.write(home, rig.path, "Add retry file", front=front, **task)
    done = home.ak("run", str(path), *args, timeout=300)
    run_dir = taskfile.only_run(home)
    return done, run_dir, json.loads((run_dir / "run.json").read_text()), fakes


class ChangeOutsideFiles(unittest.TestCase):
    """The executor writes retry.txt at the checkout's root, for a task limited to `src/`."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.base = cls.rig.head()
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")      # a run that passed could push and merge
        cls.done, cls.run_dir, cls.state, cls.fakes = launch(cls.home, cls.rig, "work",
                                                              {"files": "src/"})

    def test_the_gate_fails_naming_the_path_though_every_check_passed(self):
        lines = (self.run_dir / "round-1/donewhen.log").read_text().splitlines()
        self.assertIn("$ test -f retry.txt", lines)
        self.assertEqual(lines[lines.index("$ test -f retry.txt") + 1], "[exit 0]")
        self.assertIn("outside files: retry.txt", lines)

    def test_the_fixer_is_shown_the_path_outside_the_files(self):
        prompt = (self.run_dir / "round-1/fixer/prompt.md").read_text()
        failed = prompt.split("## The done-when commands failed.", 1)
        self.assertEqual(len(failed), 2, prompt)
        self.assertIn("outside files: retry.txt", failed[1].splitlines())

    def test_the_reviewers_pass_is_overridden_and_every_round_fails(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("fail", "FAIL"))
        self.assertEqual([(summary["verdict"], summary["done_when"])
                          for summary in self.state["round_summaries"]], [("FAIL", False)] * 3)
        reviews = self.fakes["codex"].runs()
        self.assertEqual([(run["role"], run["step"]) for run in reviews],
                         [("reviewer", "pass")] * 3)
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# FAIL — Add retry file")
        for line in ("VERDICT: FAIL", "rounds: 3 of 3", "merged: no"):
            self.assertIn(line, lines)
        self.assertTrue([line for line in lines if "outside files: retry.txt" in line], lines)

    def test_the_work_does_not_land(self):
        self.assertEqual(self.rig.head(), self.base)
        self.assertNotIn("retry.txt", self.rig.files())
        self.assertEqual(self.gh.prs(), [])
        self.assertFalse(self.state["merged"])


class ChangeInsideFiles(unittest.TestCase):
    """Every changed path matches one of the pathspecs, given on two `files:` lines."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        cls.done, cls.run_dir, cls.state, _ = launch(
            cls.home, rig, wrote("src/a.txt", "docs/guide/b.md", "lib/c.txt"),
            {"files": SPECS}, "--no-merge", done_when=("test -f src/a.txt",))

    def test_the_round_passes_with_no_path_named(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["PASS"])
        lines = (self.run_dir / "round-1/donewhen.log").read_text().splitlines()
        self.assertFalse([line for line in lines if line.startswith("outside files:")], lines)


class ChangeBothSides(unittest.TestCase):
    """Two paths outside the pathspecs among three inside, in a one-round task."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        cls.done, cls.run_dir, cls.state, _ = launch(
            cls.home, rig, wrote("src/a.txt", "z.txt", "docs/b.md", "lib/c.txt.bak",
                                 "lib/c.txt"), {"files": SPECS, "rounds": 1}, "--no-merge",
            done_when=("test -f src/a.txt",))

    def test_only_the_paths_outside_are_named_in_order(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(self.state["verdict"], "FAIL")
        lines = (self.run_dir / "round-1/donewhen.log").read_text().splitlines()
        named = [line for line in lines if line.startswith("outside files:")]
        self.assertEqual(named, ["outside files: lib/c.txt.bak, z.txt"])


if __name__ == "__main__":
    unittest.main()
