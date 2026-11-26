"""A review follow-up's fix run that fails its rounds asks its seat nothing.

ak starts a fix run for a merged run's review follow-up on its own: its seat never asked for
it.  One that fails its rounds is a routine ending, recorded with the note a routine ending has
and typed into no seat.  A task's run failing its rounds under that same seat is typed into it
as before.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, from a seat of akseat.py at its prompt, against the origin of gitrig.py
and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py; this test fails
against `/bin/false`.
"""

import json
import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SEAT = {"AGENTKIT_SESSION": "acme"}
ROUTINE = "routine ending: recorded, not typed"
FOLLOW_UP = {"final": "One for later.", "hand_in": [
    ["follow-up", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
     "test ! -f retry.txt || { wc -l < retry.txt; false; }"], ["done"]]}
# The fix run's done-when, the follow-up's command, never passes: retry.txt stays.  Changing its
# failure's output avoids the stop for identical failures before round 3.
ATTEMPT = {"sh": "printf 'attempt\\n' >> retry.txt", "commit": "try again", "final": "Tried.",
           "hand_in": [["done"]]}


def state(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def ended(run_dir, bound=300):
    """A run's ending is handed on before its log's last line names its result."""
    deadline = time.monotonic() + bound
    while time.monotonic() < deadline:
        log = run_dir / "log.txt"
        if log.exists() and log.read_text().rstrip().endswith(f" -> {run_dir / 'result.md'}"):
            return
        time.sleep(0.2)
    raise AssertionError(f"{run_dir.name} never ended: {state(run_dir).get('state')}")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AFailedFixRunAsksNothing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude=["work", ATTEMPT], codex=[FOLLOW_UP, "pass"])
        cls.seat = Seat(cls.home, "acme", cwd=cls.rig.path, record={"workers": ["opus", "astra"]},
                        planned=("test -f retry.txt", "test -f sturdy.txt"))
        merged = cls.home.ak("run", str(taskfile.write(cls.home, cls.rig.path)), env=SEAT,
                             timeout=300)
        if merged.code:
            raise AssertionError(merged.out + merged.err)
        [cls.parent] = [run for run in taskfile.runs(cls.home) if not state(run).get("followup")]
        cls.fix = cls.home.path / ".agentkit/runs" / state(cls.parent)["followup_runs"][0]
        ended(cls.fix)
        # A task whose done-when never passes either.
        task = taskfile.write(cls.home, cls.rig.path, "Harden retry file", front={"rounds": 1},
                              done_when=("test -f sturdy.txt",))
        cls.failed = cls.home.ak("run", str(task), env=SEAT, timeout=300)
        [cls.task] = [run for run in taskfile.runs(cls.home) if run not in (cls.parent, cls.fix)]
        cls.lines = cls.told(cls.task)

    @classmethod
    def told(cls, run_dir, bound=120):
        """The seat's lines once one of them hands `run_dir`'s ending back."""
        deadline = time.monotonic() + bound
        while not any(line.startswith(f"run {run_dir.name} ") for line in cls.seat.lines()):
            if time.monotonic() > deadline:
                raise AssertionError(f"{run_dir.name} was never typed: {cls.seat.lines()}")
            time.sleep(0.1)
        return cls.seat.lines()

    def test_the_fix_run_fails_its_rounds(self):
        fix = state(self.fix)
        self.assertEqual(fix["followup"]["run"], self.parent.name)
        self.assertEqual((fix["state"], fix["merged"], fix["rounds"]), ("fail", False, 3))
        self.assertEqual([done["verdict"] for done in fix["round_summaries"]], ["FAIL"] * 3)

    def test_nothing_is_typed_into_the_seat_for_it(self):
        # Every line typed is the merge's or the task's, the task's typed after the fix ended.
        told = [line for line in self.lines
                if not line.startswith((f"run {self.parent.name} ", f"run {self.task.name} "))]
        self.assertEqual(told, [], self.lines)

    def test_its_record_holds_the_routine_ending_s_note(self):
        fix = state(self.fix)
        self.assertEqual(fix.get("handback_note"), ROUTINE, fix)
        self.assertTrue(fix.get("handed_back"), fix)
        self.assertFalse(fix.get("handback_pending"), fix)

    def test_a_task_s_run_failing_its_rounds_is_typed_into_the_seat(self):
        self.assertEqual(self.failed.code, 1, self.failed.out + self.failed.err)
        self.assertEqual(state(self.task)["state"], "fail")
        [line] = [line for line in self.lines if line.startswith(f"run {self.task.name} ")]
        self.assertRegex(line, rf"^run {re.escape(self.task.name)} FAIL \(1 of 1\): ")


if __name__ == "__main__":
    unittest.main()
