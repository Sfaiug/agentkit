"""A fix run's review starts no further fix runs: follow-ups go one level deep.

A task's run whose review hands in a follow-up merges, and its seat gets a fix run of its own
for the follow-up, as `test_key_a_follow_up_is_no_plan_line` proves.  That fix run is reviewed
too, and its review hands in a follow-up of its own; the fix run merges, and nothing more: the
seat's plan holds no line for the new follow-up, no run starts for it, and the fix run's result
lists it and says it starts no run.
A chain of fix runs, each starting more, would keep a seat's work from ever ending.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from a
seat of akseat.py, against the origin of gitrig.py and the GitHub of fakegh.py, with scripted
harnesses from fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import os
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PLAN_LINE, Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

CHECK = "test -f sturdy.txt"
REVIEW = {"final": "One more defect.", "hand_in": [
    ["follow-up", "retry.txt:1", "flimsy widget", "it breaks later", "--run", CHECK],
    ["done"]]}
# failing on the fix run's base and on its commit alike: beside the fix, not caused by it
AGAIN = "grep -qx tight gears.txt"
FIX_REVIEW = {"final": "Another defect beside the fix.", "hand_in": [
    ["follow-up", "gears.txt:1", "loose gear", "it rattles", "--run", AGAIN], ["done"]]}
FIX = {"write": {"sturdy.txt": "ok\n"}, "commit": "make the widget sturdy",
       "final": "## Summary\nsturdy", "hand_in": [["done"]]}


def wait_for(read, bound=600):
    """`read()` once it is true, or the last thing it said after `bound` seconds."""
    deadline = time.monotonic() + bound
    while not (seen := read()) and time.monotonic() < deadline:
        time.sleep(0.1)
    return seen


def alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, TypeError):
        return False
    except PermissionError:
        pass
    return True


def state(run_dir):
    return json.loads((run_dir / "run.json").read_text())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AFixRunStartsNoFixRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={"gears.txt": "loose\n"})
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        Seat(cls.home, "acme", cwd=cls.rig.path, record={"reviewers": ["astra"]}, planned=True)
        fakeadapter.install(cls.home, claude=["work", FIX], codex=[REVIEW, FIX_REVIEW, "pass"])
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"}, timeout=600)
        cls.addClassCleanup(cls.settle)
        runs = taskfile.runs(cls.home)
        cls.parent_dir = next((run for run in runs if not state(run).get("followup")), None)
        fixes = [run for run in runs if state(run).get("followup")]
        cls.fix_dir = fixes[0] if len(fixes) == 1 else None
        # the fix run's ending is over once its process is: every run it would start is started
        cls.ended = cls.fix_dir and wait_for(lambda: state(cls.fix_dir).get("merged")
                                             and not alive(state(cls.fix_dir).get("pid")))

    @classmethod
    def settle(cls):
        # A run still going would outlive this Home, so it ends before the Home goes.
        for run in taskfile.runs(cls.home):
            if alive(state(run).get("pid")):
                cls.home.ak("run", "stop", run.name)

    @classmethod
    def plan(cls):
        """The seat's plan past PLAN_LINE, the line its own launch needed."""
        text = (cls.home.path / ".agentkit/state/plan-acme.md").read_text()
        return text.replace(PLAN_LINE + "\n", "", 1)

    def test_the_task_s_follow_up_gets_its_fix_run(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        parent = state(self.parent_dir)
        self.assertEqual((parent["state"], parent["merged"]), ("pass", True))
        self.assertIsNotNone(self.fix_dir, taskfile.runs(self.home))
        self.assertEqual(parent.get("followup_runs"), [self.fix_dir.name])
        self.assertIn(f"## Done when\n```bash\n{CHECK}\n```",
                      (self.fix_dir / "task.md").read_text())

    def test_the_fix_run_merges_with_its_review_s_follow_up(self):
        self.assertTrue(self.ended, state(self.fix_dir) if self.fix_dir else None)
        fix = state(self.fix_dir)
        self.assertEqual((fix["state"], fix["merged"]), ("pass", True))
        self.assertEqual([item.split(" - ")[0] for item in fix.get("followups") or []],
                         ["gears.txt:1"])
        self.assertIn("sturdy.txt", self.rig.files())

    def test_its_follow_up_writes_no_plan_line_and_starts_no_run(self):
        self.assertTrue(self.ended, state(self.fix_dir) if self.fix_dir else None)
        self.assertEqual(self.plan(), "")
        self.assertEqual(taskfile.runs(self.home), sorted([self.parent_dir, self.fix_dir]))
        self.assertFalse(state(self.fix_dir).get("followup_runs"))

    def test_the_fix_run_s_result_lists_it_and_says_it_starts_no_run(self):
        self.assertTrue(self.ended, state(self.fix_dir) if self.fix_dir else None)
        result = (self.fix_dir / "result.md").read_text()
        listed = result[result.index("## Follow-ups"):]
        self.assertIn("- gears.txt:1 - loose gear - it rattles", listed)
        self.assertIn("A fix run's follow-ups start no run", listed)
        self.assertNotIn("## Fix runs", result)


if __name__ == "__main__":
    unittest.main()
