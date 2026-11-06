"""A project's failed night starts one fix run by itself, and the owner hears nothing.

A night that failed, names failures and has no run yet gets one seatless run, its done-when the
project's `tests:` with `AK_ONLY` naming a file of the first 100 names; anything else marks nothing,
so the next hour tries again, each checkout's hour its own.  Black-box: `AK_BIN` runs `ak watch` from outside through
tests/fixtures/akbin.py, on checkouts with no seat, with turns scripted by fakeadapter.py; this
test fails against `/bin/false`.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.gitrig import Rig
from fixtures.sink import Sink

SAYS_ONLY = 'cat "$AK_ONLY"'
NAMES = [f"tests/a.py::t{number}" for number in range(101)]
LONG = "nightly-integration-suite-of-the-main-branch-on-"     # past where a name would be cut


def failed(started="night-1", names=NAMES[:2]):
    return {"started": started, "passed": False, "failed": names, "host": "ignored"}


def record_of(run):
    return json.loads((run / "run.json").read_text())


class Project:
    """A checkout under ~/code with no seat, whose `nightly:` prints what `says` set."""

    def __init__(self, home, name, tests=SAYS_ONLY):
        self.home, self.name, self.read = home, name, home.root / f"night-{name}"
        self.rig = Rig(home, name, files={"AGENTS.md": self.rules(tests)})

    def rules(self, tests):
        return f"---\n{'tests: ' + tests if tests else ''}\nnightly: {self.read}\n---\n# acme\n"

    def says(self, answer, code=0):
        text = answer if isinstance(answer, str) else json.dumps(answer)
        self.read.write_text(f"#!/bin/sh\ncat <<'END'\n{text}\nEND\nexit {code}\n")
        self.read.chmod(0o755)

    def runs(self):
        return [run for run in taskfile.runs(self.home)
                if f"repo: {self.rig.path}\n" in (run / "task.md").read_text()]

    def check(self, run):
        """What running that run's done-when in this project prints, word by word."""
        task = (run / "task.md").read_text()
        line = task.partition("## Done when\n```bash\n")[2].partition("\n")[0]
        done = self.home.run("bash", "-c", line, cwd=self.rig.path)
        assert done.code == 0, done.err
        return done.out.split()


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class FailedNights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(home, ["opus", "astra"])
        fakes = fakeadapter.install(home, claude="not-needed", codex="not-needed")
        cls.acme, cls.calm = acme, calm = Project(home, "acme"), Project(home, "calm")
        cls.stuck = broken, garbled, nameless, suiteless = [
            Project(home, "broken"), Project(home, "garbled"), Project(home, "nameless"),
            Project(home, "suiteless", tests=None)]
        cls.api = api = Project(home, "api")
        cls.late = late = Project(home, "late")
        late.says({"started": "night-1", "passed": True})
        acme.says(failed(names=NAMES))
        calm.says({"started": "night-1", "passed": True})
        broken.says("the host is down", code=3)
        garbled.says("no JSON here")
        nameless.says(failed(names=[]))
        suiteless.says(failed())
        cls.first = cls.tick()
        cls.next_hour = cls.tick(hour_on=True)
        acme.says(failed("night-2"))
        cls.same_hour = cls.tick()
        for project in cls.stuck:
            project.says(failed())
        suiteless.rig.commit({"AGENTS.md": suiteless.rules(SAYS_ONLY)})
        cls.later = cls.tick(hour_on=True)
        cls.handled = cls.tick(hour_on=True)
        # a run under way, on the host's processes, which `home.tick()`'s box hides
        release = fakes["claude"].dir / "release"
        fakes["claude"].behave({"sh": f"until [ -e {release} ]; do sleep 0.1; done",
                                "hand_in": [["not-needed", "the night is gone"]]})
        api.says(failed(LONG + "1", names=["tests/a.py::first"]))
        cls.tick(hour_on=True, seen=True)
        api.says(failed(LONG + "2", names=["tests/b.py::second"]))
        cls.under_way = cls.tick(hour_on=True, seen=True)
        cls.kept = api.check(api.runs()[0])
        release.write_text("")
        cls.ended()
        cls.after_it = cls.tick(hour_on=True, seen=True)
        cls.ended()
        # a read that yields no usable night says so, which shows each read from outside
        broken.says("the host is down", code=3)
        garbled.says("no JSON here")
        cls.one_just_read = cls.tick(hour_on=True, just_read=garbled)
        # the owner marks nobody to execute: `ak run` from no seat is refused, this run is not
        akconfig.write(home, ["opus", "astra"], workers=[], reviewers=["astra"])
        calm.says(failed())
        cls.tick(hour_on=True, seen=True)
        cls.ended()
        # the marked reviewer is signed out: no run can start, and nothing retries one that tried
        fakes["codex"].answer("auth", "signed out", code=1)
        late.says(failed())
        cls.signed_out = cls.tick(hour_on=True, seen=True)
        refused = late.runs()
        fakes["codex"].answer("auth", "signed in")
        cls.signed_in = cls.tick(hour_on=True, seen=True)
        cls.ended(refused)

    @classmethod
    def tick(cls, hour_on=False, seen=False, just_read=None):
        """Each project's (runs so far, lines saying something is wrong) after one tick."""
        if hour_on:     # the nights are read hourly: the note of the last read says long ago
            path = cls.home.path / ".agentkit" / "state" / "nightly.json"
            asked = {str(just_read.rig.path): time.time()} if just_read else 0
            path.write_text(json.dumps({**json.loads(path.read_text()), "asked": asked}))
        done = cls.home.ak("watch", boxed=True) if seen else cls.home.tick()
        assert done.code == 0, done.out + done.err
        return {project.name: (len(project.runs()), sum(
                    line.startswith(f"WARN {project.name}:") for line in done.out.splitlines()))
                for project in (cls.acme, cls.calm, cls.api, cls.late, *cls.stuck)}

    @classmethod
    def ended(cls, refused=()):
        """Every run but those refused at launch ends not needed, as a first turn finding the
        night gone on the tip says."""
        deadline = time.monotonic() + 120
        while any(record_of(run)["state"] != "not_needed"
                  for run in taskfile.runs(cls.home) if run not in refused):
            assert time.monotonic() < deadline, "a run never ended"
            time.sleep(0.1)

    def test_its_task_is_filed_under_the_project_names_each_failure_and_hands_the_tests_100(self):
        run = self.acme.runs()[0]
        task = (run / "task.md").read_text()
        self.assertIn("night-1", task)
        for name in NAMES:
            self.assertIn(f"- {name}\n", task)
        self.assertEqual(Path(record_of(run)["task_file"]).parent,
                         self.home.path / ".agentkit" / "tasks" / "acme")
        self.assertEqual(self.acme.check(run), NAMES[:100])

    def test_a_night_starts_one_run_the_next_hour_none_a_later_night_past_the_hour_another(self):
        self.assertEqual(self.first["acme"], (1, 0))
        self.assertEqual(self.next_hour["acme"], (1, 0))
        self.assertEqual(self.same_hour["acme"], (1, 0))
        self.assertEqual(self.later["acme"], (2, 0))
        self.assertIn("night-2", (self.acme.runs()[1] / "task.md").read_text())

    def test_a_passed_night_starts_none_and_says_nothing(self):
        self.assertEqual({tick["calm"] for tick in (self.first, self.handled)}, {(0, 0)})

    def test_a_night_that_cannot_start_a_run_starts_none_and_says_so_each_hour(self):
        for project in self.stuck:
            self.assertEqual(self.first[project.name], (0, 1), project.name)
            self.assertEqual(self.next_hour[project.name], (0, 1), project.name)

    def test_once_it_can_the_next_hour_starts_the_run_and_a_handled_night_says_nothing(self):
        for project in self.stuck:
            self.assertEqual(self.later[project.name], (1, 0), project.name)
            self.assertEqual(self.handled[project.name], (1, 0), project.name)

    def test_a_checkout_past_its_hour_is_read_and_one_just_read_is_not(self):
        self.assertEqual(self.one_just_read["broken"], (1, 1))
        self.assertEqual(self.one_just_read["garbled"], (1, 0))

    def test_a_later_night_with_its_own_task_file_starts_while_the_first_runs(self):
        self.assertEqual(self.under_way["api"], (2, 0))
        self.assertEqual(self.after_it["api"], (2, 0))

    def test_each_night_s_fix_has_a_branch_of_its_own(self):
        self.assertEqual(len({record_of(run)["branch"] for run in self.api.runs()}), 2)

    def test_a_later_night_leaves_the_running_fix_its_own_failures(self):
        self.assertEqual(self.kept, ["tests/a.py::first"])
        self.assertEqual(self.api.check(self.api.runs()[1]), ["tests/b.py::second"])

    def test_with_nobody_marked_to_execute_the_marked_orchestrator_builds_it(self):
        record = record_of(self.calm.runs()[0])
        self.assertEqual((record["workers"], record["reviewers"], record["executor"]),
                         (["opus"], ["astra"], "opus"))

    def test_a_reviewer_signed_out_says_so_and_the_next_hour_after_they_return_fixes_the_night(self):
        self.assertEqual(self.signed_out["late"], (1, 1))
        self.assertEqual(self.signed_in["late"], (2, 0))
        self.assertEqual([record_of(run)["state"] for run in self.late.runs()],
                         ["error", "not_needed"])

    def test_no_seat_is_opened_and_no_card_reaches_the_owner(self):
        self.assertEqual(self.sink.requests, [])
        self.assertEqual(self.home.tmux("list-sessions").out, "")
        for run in taskfile.runs(self.home):
            self.assertIsNone(record_of(run)["launched_session"])


if __name__ == "__main__":
    unittest.main()
