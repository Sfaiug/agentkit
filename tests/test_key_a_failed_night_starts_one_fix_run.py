"""A project's failed night starts one fix run by itself, and the owner hears nothing.

A night that failed, names failures and has no run yet gets one seatless run, its done-when the
project's `tests:` with `AK_ONLY` naming a file of the first 100 names; anything else marks nothing,
so the next hour tries again.  Black-box: `AK_BIN` runs `ak watch` from outside through
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
        cls.api = api = Project(home, "api")     # fewest title words `ak run` calls one change
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
        api.says(failed("night-1"))
        cls.tick(hour_on=True, seen=True)
        api.says(failed("night-2"))
        cls.under_way = cls.tick(hour_on=True, seen=True)
        release.write_text("")
        cls.ended()
        cls.after_it = cls.tick(hour_on=True, seen=True)
        cls.ended()

    @classmethod
    def tick(cls, hour_on=False, seen=False):
        """Each project's (runs so far, lines saying something is wrong) after one tick."""
        if hour_on:     # the nights are read hourly: the note of the last read says long ago
            path = cls.home.path / ".agentkit" / "state" / "nightly.json"
            path.write_text(json.dumps({**json.loads(path.read_text()), "asked": 0}))
        done = cls.home.ak("watch", boxed=True) if seen else cls.home.tick()
        assert done.code == 0, done.out + done.err
        return {project.name: (len(project.runs()), sum(
                    line.startswith(f"WARN {project.name}:") for line in done.out.splitlines()))
                for project in (cls.acme, cls.calm, cls.api, *cls.stuck)}

    @classmethod
    def ended(cls):
        """Every run ends not needed, as a first turn finding the night gone on the tip says."""
        deadline = time.monotonic() + 120
        while any(record_of(run)["state"] != "not_needed" for run in taskfile.runs(cls.home)):
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
        line = task.partition("## Done when\n```bash\n")[2].partition("\n")[0]
        done = self.home.run("bash", "-c", line, cwd=self.acme.rig.path)
        self.assertEqual((done.code, done.out.split()), (0, NAMES[:100]), done.err)

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

    def test_a_later_night_while_a_run_is_under_way_starts_once_that_run_ended(self):
        self.assertEqual(self.under_way["api"], (1, 1))
        self.assertEqual(self.after_it["api"], (2, 0))

    def test_no_seat_is_opened_and_no_card_reaches_the_owner(self):
        self.assertEqual(self.sink.requests, [])
        self.assertEqual(self.home.tmux("list-sessions").out, "")
        for run in taskfile.runs(self.home):
            self.assertIsNone(record_of(run)["launched_session"])


if __name__ == "__main__":
    unittest.main()
