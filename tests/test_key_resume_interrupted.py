"""`ak run resume ID` carries an interrupted run on from where it was cut off, and finishes it.

A run's process can die at any moment: the host reboots, memory runs out, someone kills it.
What the executor already built must not be built again, and the round it was in must not be
spent twice: the resume picks up at that round, on the same worktree and branch, runs the
review the run was in the middle of on the reviewer's own conversation, and ends the run as if
nothing had happened, still not delivered when it was started with --no-merge.  Here the run
is killed while its reviewer is at work.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, on a project from gitrig.py, a config from
akconfig.py, a task from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


class ResumeInterrupted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        reviewing = cls.home.root / "adapters" / "reviewing"
        # The first review only says it began and waits there, as a turn does when its run
        # dies under it; bounded, so nothing outlives the test if a build left it orphaned.
        held = {"sh": f"touch {reviewing}; sleep 60"}
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex=[held, "pass"])
        cls.task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        proc = cls.home.spawn("run", str(cls.task), "--no-merge")
        deadline = time.monotonic() + 120
        while not reviewing.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("the run never reached its review: "
                                     + cls.home.log("spawn-1.err").read_text())
            time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        cls.run_dir = taskfile.only_run(cls.home)
        cls.worktree = cls.home.path / ".agentkit/wt" / cls.run_dir.name
        cls.done = cls.home.ak("run", "resume", cls.run_dir.name, timeout=300)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_resumed_run_passes_in_the_round_it_was_cut_off_in(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([(entry["round"], entry["verdict"], entry["done_when"])
                          for entry in self.state["round_summaries"]], [(1, "PASS", True)])
        lines = (self.run_dir / "result.md").read_text().splitlines()
        for line in ("VERDICT: PASS", "rounds: 1 of 3"):
            self.assertIn(line, lines)

    def test_it_says_where_it_resumed(self):
        line = f"resuming at round 1/3: {self.worktree} on ak/add-retry-file"
        self.assertIn(line, self.done.out)
        self.assertIn(line, (self.run_dir / "log.txt").read_text())

    def test_the_next_turn_is_the_review_on_the_reviewers_own_conversation(self):
        self.assertEqual(self.fakes["claude"].n, 1)
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()], ["executor"])
        self.assertEqual(self.fakes["codex"].n, 2)
        # The interrupted review never finished, so the one finished call is the resumed one.
        resumed = self.fakes["codex"].runs()
        self.assertEqual([run["role"] for run in resumed], ["reviewer"])
        self.assertEqual(resumed[0]["argv"][5:], ["sid-codex-1"])

    def test_what_was_reviewed_is_the_executors_commit_from_before_the_interruption(self):
        head = self.home.run("git", "-C", str(self.worktree), "rev-parse", "HEAD").out.strip()
        self.assertEqual(self.state["round_summaries"][0]["head_sha"], head)
        built = self.home.run("git", "-C", str(self.worktree), "log", "--format=%s",
                              f"{self.rig.head('main')}..HEAD")
        self.assertEqual(built.out.splitlines(), ["add retry.txt"])

    def test_the_resume_keeps_the_run_undelivered_as_it_was_launched(self):
        self.assertEqual((self.state["no_merge"], self.state["merged"], self.state["pr"]),
                         (True, False, None))
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertIn("ak/add-retry-file", self.rig.branches(remote=False))
        self.assertFalse([call for call in self.home.calls("gh")
                          if call[:2] in (["pr", "create"], ["pr", "merge"])])


if __name__ == "__main__":
    unittest.main()
