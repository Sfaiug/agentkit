"""A reviewer's follow-up becomes a check line in its seat's plan, deferred while a fix run has it.

A follow-up is work the review found beyond the task, and the seat that launched the run owns
it: when the run merges, ak writes it into that seat's plan as an open line whose check is the
reviewer's failing `--run` command, naming the commit it failed on.  Where the seat has
executors a fix run of its own starts with that command as its done-when, and the line is
deferred to it, so the seat owes nothing while the run is on its way; once that run merges, the
line is ticked done by its merge.  A seat with no executor gets the line as its own to build,
and no run starts.  Losing the line would drop the reviewer's work without a word.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from a seat of
akseat.py, against the origin of gitrig.py and the GitHub of fakegh.py, with scripted
harnesses from fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import os
import re
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
OUTCOME = "Fix retry.txt:1 - flimsy widget - it breaks later"
REVIEW = {"final": "One more defect.", "hand_in": [
    ["follow-up", "retry.txt:1", "flimsy widget", "it breaks later", "--run", CHECK],
    ["done"]]}
# The plan line as plan.py documents it: box, outcome, check, project, mark, when, commit, done.
LINE = re.compile(r"- \[(?P<mark>[ x])\] (?P<what>.+?) · check: `(?P<check>[^`]+)` · "
                  r"(?P<project>\S+)(?P<deferred> · deferred)? · written "
                  r"\d{4}-\d\d-\d\d \d\d:\d\d on (?P<base>[0-9a-f]{12})(?: · done (?P<done>.+))?")


def wait_for(read, bound=120):
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


class Seated:
    """A project, a GitHub, and the seat `name` filed in it, reviewed by astra."""

    @classmethod
    def seat(cls, name):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        Seat(cls.home, name, cwd=cls.rig.path, record={"reviewers": ["astra"]})
        cls.name, cls.release = name, cls.home.root / "adapters" / "release"
        cls.task = taskfile.write(cls.home, cls.rig.path, "Add retry file")

    @classmethod
    def plan(cls):
        try:
            return (cls.home.path / f".agentkit/state/plan-{cls.name}.md").read_text()
        except FileNotFoundError:
            return ""

    @classmethod
    def state(cls, run_dir):
        return json.loads((run_dir / "run.json").read_text())

    def only_line(self, text):
        lines = [line for line in text.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, text)
        found = LINE.fullmatch(lines[0])
        self.assertIsNotNone(found, lines[0])
        return found

    def assertTheFollowUp(self, found, parent):
        self.assertEqual((found["what"], found["check"]), (OUTCOME, CHECK))
        self.assertEqual(found["project"].split("#")[0], "~/code/widgets")
        # the commit the reviewer's command was proven failing on: the one reviewed
        self.assertEqual(found["base"], parent["review"]["head_sha"][:12])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatWithExecutors(Seated, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seat("acme")
        fix = {"write": {"sturdy.txt": "ok\n"}, "commit": "make the widget sturdy",
               "final": "## Summary\nsturdy", "hand_in": [["done"]]}
        fakeadapter.install(cls.home, claude=["work", held(cls.release, fix)],
                            codex=[REVIEW, "pass"])
        cls.done = cls.home.ak("run", str(cls.task), env={"AGENTKIT_SESSION": "acme"},
                               timeout=300)
        cls.held_plan = cls.plan()
        cls.addClassCleanup(cls.settle)
        cls.parent_dir, *fixes = taskfile.runs(cls.home)
        cls.fix_dir = fixes[0] if len(fixes) == 1 else None
        cls.fix_held = cls.state(cls.fix_dir) if cls.fix_dir else {}
        cls.release.write_text("")
        cls.ticked = cls.fix_dir and wait_for(lambda: cls.plan().startswith("- [x]")
                                              and cls.plan())

    @classmethod
    def settle(cls):
        # A fix run still going would outlive this Home, so it ends before the Home goes.
        cls.release.write_text("")
        if not cls.fix_dir:
            return
        if not wait_for(lambda: not alive(cls.state(cls.fix_dir).get("pid")), 60):
            cls.home.ak("run", "stop", cls.fix_dir.name)

    def test_the_merge_writes_it_as_a_deferred_check_line_in_the_seat_s_plan(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        parent = self.state(self.parent_dir)
        self.assertEqual((parent["state"], parent["merged"]), ("pass", True))
        found = self.only_line(self.held_plan)
        self.assertEqual(found["mark"], " ")
        self.assertTrue(found["deferred"], self.held_plan)
        self.assertIsNone(found["done"])
        self.assertTheFollowUp(found, parent)
        result = (self.parent_dir / "result.md").read_text()
        self.assertIn(f"Review follow-ups now deferred in your plan: {OUTCOME}, each fixed by a "
                      "run of its own", result)

    def test_a_fix_run_of_the_seat_has_it_with_the_reviewer_s_command_as_its_done_when(self):
        self.assertIsNotNone(self.fix_dir, taskfile.runs(self.home))
        self.assertIn(self.fix_held.get("state"), ("queued", "running"))
        self.assertEqual(self.fix_held.get("launched_session"), "acme")
        task = (self.fix_dir / "task.md").read_text()
        self.assertIn(f"## Done when\n```bash\n{CHECK}\n```", task)
        self.assertEqual(self.state(self.parent_dir).get("followup_runs"), [self.fix_dir.name])
        lines = (self.parent_dir / "result.md").read_text().splitlines()
        self.assertIn(f"- {self.fix_dir.name}", lines[lines.index("## Fix runs"):])

    def test_once_the_fix_run_merges_its_line_is_ticked_done_by_that_merge(self):
        self.assertTrue(self.ticked, f"the line was never ticked: {self.plan()}")
        found = self.only_line(self.ticked)
        self.assertEqual(found["mark"], "x")
        self.assertTheFollowUp(found, self.state(self.parent_dir))
        merged = self.rig.head()
        self.assertEqual(found["done"].split()[0], merged[:12])
        self.assertIn("sturdy.txt", self.rig.files())


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
        cls.code = run.wait(300)

    def test_the_line_is_the_seat_s_own_to_build_and_no_run_starts(self):
        self.assertEqual(self.code, 0, self.home.log("spawn-1.err").read_text())
        runs = taskfile.runs(self.home)
        self.assertEqual(len(runs), 1, runs)
        parent = self.state(runs[0])
        self.assertEqual((parent["state"], parent["merged"]), ("pass", True))
        found = self.only_line(self.plan())
        self.assertEqual(found["mark"], " ")
        self.assertIsNone(found["deferred"], self.plan())
        self.assertTheFollowUp(found, parent)
        self.assertFalse(parent.get("followup_runs"))
        result = (runs[0] / "result.md").read_text()
        self.assertIn(f"Review follow-ups now in your plan, yours to build: {OUTCOME}", result)


if __name__ == "__main__":
    unittest.main()
