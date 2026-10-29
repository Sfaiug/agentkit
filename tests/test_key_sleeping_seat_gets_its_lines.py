"""Every line for a sleeping seat wakes it and goes into it after the resume, at its prompt: its
after-merge break, never into the other live seat on its repository, even once a failed wake let
its merge leave the window, and its job's ending, which pages nobody.  A seat the owner closed as
it slept stays closed, and its break goes to that other seat.  Black-box: `AK_BIN` runs from
outside (tests/fixtures/akbin.py), each tick in the box `home.tick()` builds, a seat asleep as ak
leaves one (its record marked asleep since its launch, gone from tmux, its conversation kept), on
projects from gitrig.py and the GitHub of fakegh.py."""

import json
import re
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.sink import Sink

JOB = "20261028-1200-acme-job"


def told(repo, number):
    return (f"ci failed on main after this merge: https://github.com/acme/{repo}/pull/{number}."
            " Fix the target.")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class Sleeping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(cls.home, ["opus"])
        cls.fake = fakeadapter.install(cls.home, claude="pass")["claude"]
        cls.stage()

    @classmethod
    def asleep(cls, name, cwd=None):
        seat = Seat(cls.home, name, cwd=cwd, alive=False, record={"launched": 1, "asleep": 2})
        # a conversation Claude filed under the seat's path, which the seat resumes
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        cls.home.write(f".claude/projects/{folder}/conv-{name}.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        # woken, the harness shows the seat's screen again and keeps what is typed in
        argv = [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]
        cls.fake.answer("interactive", shlex.join(argv), given=(f"conv-{name}",))
        return seat

    @classmethod
    def tick(cls):
        done = cls.home.tick()
        assert done.code == 0, done.out + done.err

    @classmethod
    def tick_until_told(cls, seat):
        """Ticks until the seat took a line: the one that wakes it may find its harness not yet
        at its prompt, and the next types it."""
        for _ in range(3):
            cls.tick()
            if seat.lines():
                return

    def awake(self, name):
        return name in self.home.tmux("list-sessions", "-F", "#{session_name}").out.split()

    def pages(self):
        return [r for r in self.sink.requests if r.method == "POST"]


class AfterMergeBreak(Sleeping):
    @classmethod
    def stage(cls):
        cls.gh, cls.seats = GitHub(cls.home), {}
        for repo, sleeper, other in (("app", "acme", "beta"), ("api", "gamma", "delta")):
            rig = Rig(cls.home, repo)
            cls.seats[other] = Seat(cls.home, other, cwd=rig.path)
            cls.seats[sleeper] = cls.asleep(sleeper)
            cls.merge(rig, other, 1, "success", age=1200)
            cls.merge(rig, sleeper, 2, "failure", age=600)
        done = cls.home.ak("orch", "stop", "gamma")    # the owner closes it as it sleeps
        assert done.code == 0, done.out + done.err
        # acme's first wake fails, and its merge leaves the window before the next one
        acme = cls.seats["acme"].cwd
        gone = acme.rename(cls.home.path / "gone")
        cls.tick()
        gone.rename(acme)
        run = cls.home.path / ".agentkit/runs/20261028-1200-app-2/run.json"
        cls.home.write(run, {**json.loads(run.read_text()), "finished_at": time.time() - 4 * 3600})
        cls.tick_until_told(cls.seats["acme"])

    @classmethod
    def merge(cls, rig, seat, number, conclusion, age):
        sha = rig.commit({f"pr-{number}.txt": f"{number}\n"}, f"Merge {number}")
        cls.gh.check(sha, "ci", conclusion=conclusion)
        now, run = time.time(), f"20261028-1200-{rig.name}-{number}"
        cls.home.write(f".agentkit/runs/{run}/run.json", {
            "run_id": run, "state": "pass", "verdict": "PASS", "merged": True,
            "finished_at": now - age, "started_at": now - age - 600, "repo": str(rig.path),
            "pr": f"https://github.com/acme/{rig.name}/pull/{number}", "merge_sha": sha,
            "launched_session": seat})

    def test_a_sleeping_seat_is_woken_and_its_break_typed_in(self):
        self.assertTrue(self.awake("acme"))
        self.assertEqual(self.seats["acme"].wait_lines(1), [told("app", 2)])
        self.assertEqual(self.seats["beta"].lines(), [])

    def test_the_break_of_a_seat_the_owner_closed_goes_to_the_other_seat(self):
        self.assertFalse(self.awake("gamma"))
        self.assertEqual(self.seats["delta"].wait_lines(1), [told("api", 2)])

    def test_no_break_pages_the_owner(self):
        self.assertEqual(self.pages(), [])


class JobEnding(Sleeping):
    @classmethod
    def stage(cls):
        cls.seat = cls.asleep("acme")
        # a job whose one task cannot start (it waits on an `after:` no job keeps): it ends at once
        cls.home.write(f".agentkit/jobs/{JOB}/job.json", {
            "job_id": JOB, "seat": "acme", "cwd": str(cls.seat.cwd), "opts": {},
            "tasks": [{"name": "fix-api.md", "state": "queued", "after": ["fix-db.md"]}]})
        cls.ended = cls.home.ak("run", "resume", JOB)
        cls.tick_until_told(cls.seat)

    def test_a_job_ending_wakes_its_seat_and_is_typed_in_after_the_resume(self):
        self.assertEqual(self.ended.code, 1, self.ended.out + self.ended.err)   # a task blocked
        self.assertTrue(self.awake("acme"))
        line, = self.seat.wait_lines(1)
        self.assertTrue(line.startswith(f"job {JOB}: 1 task(s) need you"), line)
        self.assertEqual(self.pages(), [])      # no card for the owner


if __name__ == "__main__":
    unittest.main()
