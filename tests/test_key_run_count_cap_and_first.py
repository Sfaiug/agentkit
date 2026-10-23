"""A positive `max_runs` queues runs past the count, and `--first` goes ahead of the queue.

`max_runs` in config.toml caps how many runs go at once; 0 leaves the host's memory and ak's CPU
as the only gates.  With a cap of one, a second run waits queued on the count while the first
works, and starts once the slot frees.  A run launched with `--first` skips both the count cap
and the queue: it goes and ends while the others still hold and wait, so the run that matters
now is never stuck behind work that can wait.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, on a project from gitrig.py with scripted harnesses
from fakeadapter.py; the first run's executor turn holds until the test releases it.  The host
readings and the slot poll are ak's own knobs (AK_HOST_READINGS, AK_SLOT_POLL), set so that
only the count can hold a run and a wait is polled every half second.
"""

import json
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}
WAITING = ("queued", "running")


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class CountCapAndFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        del home.env["AK_MAX_RUNS"]
        home.env.update(AK_SLOT_POLL="0.5", AK_HOST_READINGS=json.dumps(READINGS))
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"], settings={"max_runs": 1})
        cls.fakes = fakeadapter.install(home, claude="work", codex="pass")
        release = cls.fakes["claude"].dir / "release"
        # Bounded, so a turn the test never released cannot outlive it.
        released = f"[ -f {shlex.quote(str(release))} ]"
        hold = {**fakeadapter.WORK,
                "sh": f"for i in $(seq 900); do {released} && break; sleep 0.1; done"}
        cls.fakes["claude"].behave(hold, "work")
        cls.addClassCleanup(cls.settle)
        cls.addClassCleanup(release.touch)
        cls.ids = {}
        cls.launched = {}
        for name, title, flags in (("held", "Add retry file", ()),
                                   ("queued", "Bump alpha notes", ()),
                                   ("first", "Write beta log", ("--first",))):
            known = set(taskfile.runs(home))
            task = taskfile.write(home, rig.path, title)
            # --anyway: the three check the same file, which reads as one change under way
            done = home.ak("run", str(task), "--no-merge", "--bg", "--anyway", *flags)
            cls.launched[name] = done
            cls.ids[name] = (set(taskfile.runs(home)) - known).pop()
            if name == "held":
                wait(lambda: cls.fakes["claude"].n == 1, "the held run's executor turn")
            if name == "queued":
                wait(lambda: cls.state("queued").get("state") == "queued"
                     and cls.state("queued").get("slot_wait_kind") == "count",
                     "the second run queued on the count")
        wait(lambda: cls.state("first").get("state") not in WAITING, "the --first run's end")
        cls.during = {name: cls.state(name) for name in cls.ids}
        cls.ended_turns = cls.turns()
        release.touch()
        wait(lambda: all(cls.state(name).get("state") not in WAITING for name in cls.ids),
             "every run's end")
        cls.after = {name: cls.state(name) for name in cls.ids}

    @classmethod
    def state(cls, name):
        try:
            return json.loads((cls.ids[name] / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    @classmethod
    def turns(cls):
        """The run each ended executor turn worked for, by the turn's number."""
        return {run["n"]: Path(run["argv"][2]).name for run in cls.fakes["claude"].runs()}

    @classmethod
    def settle(cls):
        """No run left going once the test is over, passed or not."""
        try:
            wait(lambda: all(cls.state(name).get("state") not in WAITING for name in cls.ids),
                 "every run's end", bound=120)
        except AssertionError:
            pass

    def test_each_launch_detaches_at_once(self):
        for name, done in self.launched.items():
            with self.subTest(name):
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertIn(self.ids[name].name, done.out)

    def test_a_run_past_the_cap_waits_queued_on_the_count_while_the_first_works(self):
        held, queued = self.during["held"], self.during["queued"]
        self.assertEqual(held.get("state"), "running")
        self.assertEqual((queued.get("state"), queued.get("slot_wait_kind")), ("queued", "count"))

    def test_a_first_run_skips_the_cap_and_the_queue_and_ends_while_they_wait(self):
        self.assertEqual(self.during["first"].get("verdict"), "PASS")
        # turn 1, the held run's, has not ended
        self.assertEqual(self.ended_turns, {2: self.ids["first"].name})

    def test_the_queued_run_starts_once_the_slot_frees_and_says_it_waited(self):
        for name in self.ids:
            with self.subTest(name):
                self.assertEqual(self.after[name].get("verdict"), "PASS")
        self.assertEqual(self.turns(), {1: self.ids["held"].name, 2: self.ids["first"].name,
                                        3: self.ids["queued"].name})
        first_lines = {name: (self.ids[name] / "log.txt").read_text().split("\n", 1)[0]
                       for name in self.ids}
        self.assertRegex(first_lines["queued"], r"\bslot\b.*\bcount\b")
        for name in ("held", "first"):
            self.assertNotRegex(first_lines[name], r"\bwaited\b")


if __name__ == "__main__":
    unittest.main()
