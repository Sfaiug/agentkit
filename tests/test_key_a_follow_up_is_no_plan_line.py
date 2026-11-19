"""A reviewer's follow-up gets a fix run of its own and never a line in its seat's plan.

A follow-up is work the review found beyond the task.  When the run merges, a seat with
executors gets a fix run with the reviewer's failing `--run` command as its done-when; a seat
with no executor gets none.  Either way the seat's plan is left as it was: a line there would
hold the seat open until it was fixed, and a reviewer must not keep a seat's work from ending.
The merged run's result lists the follow-up, and the fix run where one started.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from a seat of
akseat.py, against the origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses
from fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import os
import shlex
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

CHECK = "test -f sturdy.txt"
ITEM = "retry.txt:1 - flimsy widget - it breaks later"
REVIEW = {"final": "One more defect.", "hand_in": [
    ["follow-up", "retry.txt:1", "flimsy widget", "it breaks later", "--run", CHECK],
    ["done"]]}


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


def held(release, then):
    """A turn that waits for the test to let it go (at most 100 s), then does `then`."""
    wait = (f"i=0; while [ ! -f {shlex.quote(str(release))} ] && [ $i -lt 1000 ]; "
            "do sleep 0.1; i=$((i+1)); done")
    return {"sh": wait, **then}


def state(run_dir):
    return json.loads((run_dir / "run.json").read_text())


class Seated:
    """A project, a GitHub, and the seat `name` filed in it with a plan, reviewed by astra."""

    @classmethod
    def seat(cls, name):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        Seat(cls.home, name, cwd=cls.rig.path, record={"reviewers": ["astra"]}, planned=True)
        cls.release = cls.home.root / "adapters" / "release"
        cls.task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.plan_file = cls.home.path / f".agentkit/state/plan-{name}.md"
        cls.before = cls.plan_file.read_text()

    def section(self, result, heading):
        """The lines of `result`'s section under `heading`."""
        lines = result.splitlines()
        self.assertIn(heading, lines, result)
        rest = lines[lines.index(heading) + 1:]
        return rest[:next((n for n, line in enumerate(rest) if line.startswith("## ")), len(rest))]

    def assertListsTheFollowUp(self, result):
        self.assertIn(f"- {ITEM}", self.section(result, "## Follow-ups"))
        self.assertNotIn("## Follow-up plan", result.splitlines())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatWithExecutors(Seated, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seat("acme")
        # The fix run's turn waits for the test, so what the merge started is still there to read.
        fakeadapter.install(cls.home, claude=["work", held(cls.release, fakeadapter.PASS)],
                            codex=[REVIEW, "pass"])
        cls.done = cls.home.ak("run", str(cls.task), env={"AGENTKIT_SESSION": "acme"},
                               timeout=600)
        cls.addClassCleanup(cls.settle)
        cls.plan = cls.plan_file.read_text()
        cls.parent_dir, *fixes = taskfile.runs(cls.home)
        cls.fix_dir = fixes[0] if len(fixes) == 1 else None

    @classmethod
    def settle(cls):
        # A fix run still going would outlive this Home, so it ends before the Home goes.
        for run in taskfile.runs(cls.home):
            if alive(state(run).get("pid")):
                cls.home.ak("run", "stop", run.name)
        cls.release.write_text("")

    def test_the_run_merges_with_its_follow_up(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        parent = state(self.parent_dir)
        self.assertEqual((parent["state"], parent["merged"]), ("pass", True))
        self.assertEqual([item.splitlines()[0] for item in parent["followups"]], [ITEM])

    def test_a_fix_run_has_it_with_the_reviewer_s_command_as_its_done_when(self):
        self.assertIsNotNone(self.fix_dir, taskfile.runs(self.home))
        fix = state(self.fix_dir)
        self.assertIn(fix.get("state"), ("queued", "running"))
        self.assertEqual(fix.get("launched_session"), "acme")
        self.assertIn(f"## Done when\n```bash\n{CHECK}\n```", (self.fix_dir / "task.md").read_text())
        self.assertEqual(state(self.parent_dir).get("followup_runs"), [self.fix_dir.name])

    def test_the_seat_s_plan_is_as_it_was_before_the_merge(self):
        self.assertEqual(self.plan, self.before)

    def test_the_result_lists_the_follow_up_and_its_fix_run(self):
        self.assertIsNotNone(self.fix_dir, taskfile.runs(self.home))
        result = (self.parent_dir / "result.md").read_text()
        self.assertListsTheFollowUp(result)
        self.assertIn(f"- {self.fix_dir.name}", self.section(result, "## Fix runs"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatWithoutExecutors(Seated, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seat("beta")
        fakes = fakeadapter.install(cls.home, claude=[held(cls.release, fakeadapter.WORK)],
                                    codex=[REVIEW])
        run = cls.home.spawn("run", str(cls.task), env={"AGENTKIT_SESSION": "beta"})
        # The owner unmarks the seat's executors while its run is in flight.
        wait_for(lambda: fakes["claude"].n == 1 or run.poll() is not None)
        record = cls.home.path / ".agentkit/state/session-beta.json"
        cls.home.write(record.relative_to(cls.home.path),
                       {**json.loads(record.read_text()), "workers": []})
        cls.release.write_text("")
        cls.code = run.wait(600)

    def test_the_merge_starts_no_run_and_leaves_the_plan_as_it_was(self):
        self.assertEqual(self.code, 0, self.home.log("spawn-1.err").read_text())
        [run] = taskfile.runs(self.home)
        parent = state(run)
        self.assertEqual((parent["state"], parent["merged"]), ("pass", True))
        self.assertEqual(parent.get("followup_runs"), [])     # handed on, to no run
        self.assertEqual(self.plan_file.read_text(), self.before)
        self.assertListsTheFollowUp((run / "result.md").read_text())


if __name__ == "__main__":
    unittest.main()
