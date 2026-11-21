"""A task's run whose review leaves `rescope_findings` blocking findings or more spends no further round.

With ak's six, a run whose first review leaves six ends FAIL after that round, as a run that
spent its rounds ends: its budget is the one round it recorded, its result says why in one
sentence -- the count, the number, and that the task is to be rescoped --, its next step is to
split the task, and its resume is refused in that sentence, whatever its `--rounds`, its worktree
cleaned or not, with no worker box, whichever version ended it, and started before the run
ended too.  One left five goes on to its second round, as does one left six
under `rescope_findings = 0`; a project's front matter of four ends a run its review left four.
Under two, two left at the third round end the run there, with no extra round
(tests/test_key_one_finding_left_gets_extra_rounds.py) after it.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py
with the GitHub of fakegh.py, a config from akconfig.py, a task from taskfile.py and scripted
harnesses from fakeadapter.py.
"""

import json
import shlex
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
import test_key_one_finding_left_gets_extra_rounds as extra

LINES = 6
WORK = {"write": {"retry.txt": "wrong\n" * LINES}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
FIX = {"write": {"retry.txt": "ready\n" * LINES}, "commit": "fix retry.txt",
       "final": "## Summary\nfixed retry.txt", "hand_in": [["done"]]}


def review(count):
    """A review leaving `count` blocking findings, one on each of retry.txt's first lines, each
    proven until its line reads `ready`."""
    return {"final": f"Found {count}.", "hand_in": [
        *(["finding", f"retry.txt:{n}", f"line {n} is wrong", "breaks callers", "--run",
           f"sed -n {n}p retry.txt | grep -qx ready"] for n in range(1, count + 1)), ["done"]]}


def run(cls, count, settings=None, files=None):
    """One run of `Add retry file` whose first review leaves `count` findings and whose second
    passes: opus builds and fixes, astra alone reviews."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets", files=files)
    if files:
        cls.rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    GitHub(cls.home).grant(cls.rig.slug, "WRITE")
    akconfig.write(cls.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                   settings=settings)
    cls.fakes = fakeadapter.install(cls.home, claude=[WORK, FIX], codex=[review(count), "pass"])
    task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
    cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=600)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = json.loads((cls.run_dir / "run.json").read_text())
    cls.result = (cls.run_dir / "result.md").read_text()


def older(home):
    """An older ak's checkout, whose bin/ak would carry a resume on: the file it leaves as it runs."""
    ran = home.root / "older-ak" / "ran"
    home.write(ran.parent / "bin/ak", f"from pathlib import Path\nPath({str(ran)!r}).touch()\n")
    return ran


def refused(case, home, run_dir, *more):
    resumed = home.ak("run", "resume", run_dir.name, *more, timeout=300)
    case.assertEqual(resumed.code, 2, resumed.out + resumed.err)
    case.assertIn("The review left 6 blocking findings, at or past rescope_findings = 6: "
                  "rescope the task.", resumed.err)


def rounds(state):
    return [(row["round"], row["verdict"], row["finding_count"]) for row in state["round_summaries"]]


class Ends:
    """The run ends FAIL after its first round, and its result says why."""
    count = number = 0

    def test_the_run_ends_failed_after_its_first_round(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", self.count)])
        self.assertEqual((self.state["state"], self.state["merged"]), ("fail", False))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))
        self.assertIn("rounds: 1 of 1", self.result.splitlines())

    def test_its_result_says_why(self):
        lines = self.result.splitlines()
        at = lines.index("## Why this run stopped")
        self.assertEqual(lines[at + 2], f"The review left {self.count} blocking findings, at or past "
                                        f"rescope_findings = {self.number}: rescope the task.")

    def test_its_result_offers_no_more_rounds(self):
        self.assertEqual(self.result.splitlines()[2], "Next: split the task")
        self.assertNotIn("ak run resume", self.result)


class GoesOn:
    """The run goes on to its second round, which passes."""
    count = 0

    def test_the_run_goes_on_to_its_second_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", self.count), (2, "PASS", 0)])
        self.assertEqual(self.state["state"], "pass")
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (2, 2))


class SixLeft(Ends, unittest.TestCase):
    count = number = 6

    @classmethod
    def setUpClass(cls):
        run(cls, 6)

    def test_its_resume_is_refused_for_rescoping(self):
        for more in ((), ("--rounds", "3"), ("--rounds", "4")):
            with self.subTest(more=more):
                refused(self, self.home, self.run_dir, *more)
                self.assertEqual(json.loads((self.run_dir / "run.json").read_text()), self.state)
        # its record naming an older ak, which never runs, its worktree cleaned or not, and with
        # no worker box to be had
        ran = older(self.home)
        record = {**self.state, "ak_checkout": str(ran.parent)}
        self.home.write(self.run_dir / "run.json", record)
        for step in ("older", "cleaned", "no box"):
            with self.subTest(step):
                if step == "cleaned":
                    self.assertEqual(self.home.ak("run", "clean", self.run_dir.name).code, 0)
                if step == "no box":
                    self.home.fake("bwrap", "#!/bin/sh\nexit 1\n")
                refused(self, self.home, self.run_dir, "--rounds", "3")
                self.assertFalse(ran.exists())
                self.assertEqual(json.loads((self.run_dir / "run.json").read_text()), record)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))


# What a resume's Python loads first: it stops itself at the call STOP_AT names, as a debugger would.
STOP = """import os, signal, sys
STOP_AT = tuple(os.environ["STOP_AT"].split())
def stop(frame, event, _arg):
    if (frame.f_globals.get("__name__"), frame.f_code.co_name, event,
            frame.f_back and frame.f_back.f_code.co_name) == STOP_AT:
        sys.setprofile(None)
        os.kill(os.getpid(), signal.SIGSTOP)
sys.setprofile(stop)
"""


class SixLeftAsItsResumeStarts(unittest.TestCase):
    """A resume started while the first review still goes, its record naming an older ak, and
    stopped until the run has ended on six is refused as one started after: stopped as ak picks
    the version to run it on, at its box check, or as it asks whether the run's loop lives."""

    def test_it_is_refused(self):
        for at in ("agentkit.record read_state return dispatch", "agentkit.box check call resume_run",
                   "agentkit.record process_active call resume_run"):
            with self.subTest(at=at):
                self.stopped_at(at)

    def stopped_at(self, at):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakes = fakeadapter.install(home, claude=[WORK, FIX], codex="pass")
        reviewing, release = (fakes["codex"].dir / name for name in ("reviewing", "release"))
        fakes["codex"].behave({**review(6), "sh": f"touch {shlex.quote(str(reviewing))}; until [ -f "
                               f"{shlex.quote(str(release))} ]; do sleep .05; done"}, "pass")
        launch = home.spawn("run", str(taskfile.write(home, rig.path, "Add retry file")), "--no-merge")
        until(reviewing.exists)
        run_dir = taskfile.only_run(home)
        ran = older(home)
        record = {**json.loads((run_dir / "run.json").read_text()), "ak_checkout": str(ran.parent)}
        home.write(run_dir / "run.next", record).replace(run_dir / "run.json")
        hook = home.write("stop/sitecustomize.py", STOP)
        resume = home.spawn("run", "resume", run_dir.name, "--rounds", "3",
                            env={"PYTHONPATH": str(hook.parent), "STOP_AT": at})
        try:
            until(lambda: resume.poll() is not None
                  or ") T " in Path(f"/proc/{resume.pid}/stat").read_text())
        finally:
            release.touch()
        self.assertEqual(launch.wait(timeout=300), 1)
        resume.send_signal(signal.SIGCONT)
        self.assertEqual(resume.wait(timeout=300), 2, home.log("spawn-2.err").read_text())
        self.assertIn("rescope_findings = 6: rescope the task.", home.log("spawn-2.err").read_text())
        self.assertFalse(ran.exists())
        state = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((state["state"], rounds(state)), ("fail", [(1, "FAIL", 6)]))


def until(check):
    deadline = time.monotonic() + 300
    while not check():
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.05)


class FiveLeft(GoesOn, unittest.TestCase):
    count = 5

    @classmethod
    def setUpClass(cls):
        run(cls, 5)


class SixLeftWithRescopeOff(GoesOn, unittest.TestCase):
    count = 6

    @classmethod
    def setUpClass(cls):
        run(cls, 6, settings={"rescope_findings": 0})


class FourLeftUnderAProjectsFour(Ends, unittest.TestCase):
    count = number = 4

    @classmethod
    def setUpClass(cls):
        run(cls, 4, files={"AGENTS.md": "---\ntests: none\nhealth: none\nusers: none\n"
                                        "rescope_findings: 4\n---\nA project.\n"})


class TwoLeftAtTheThirdRoundUnderTwo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        two = {"final": "Found two.", "hand_in": [extra.finding("retry.txt"),
                                                  extra.finding("other.txt"), ["done"]]}
        extra.run(cls, [extra.WORK, extra.DISPUTE, extra.DISPUTE_ADDING],
                  [extra.ONE, extra.ONE, two, "pass"], {"rescope_findings": 2}, "--no-merge")

    def test_the_run_ends_failed_after_three_with_no_extra_round(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 2)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 3))
        self.assertEqual(self.state["error"], "The review left 2 blocking findings, at or past "
                                              "rescope_findings = 2: rescope the task.")


if __name__ == "__main__":
    unittest.main()
