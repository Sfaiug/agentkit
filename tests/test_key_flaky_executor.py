"""An executor that fails on its provider is retried once, then handed to another model.

A provider that answers with an empty exit or a 500 is having a bad minute, not judging the
task: the run waits a minute and resumes the same session, and while it waits run.json says
until when, so the tick does not read the wait as silence.  A second failure in a row hands the
round to a worker on another provider, in a fresh session, and the reviewer is picked again so
the new executor never reviews its own work.  The run then carries on in the same round.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, with scripted harnesses from fakeadapter.py.  Today's ak sleeps the
whole minute (there is no seam to shorten it), so this file takes a little over a minute.
"""

import json
import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

RETRY = ("WARN executor opus exited 1 with an empty final.md (attempt 1); retrying in 60s, "
         "resuming session sid-flaky-1")
REPICK = "reviewer re-picked for executor astra: astra -> spark"


def record(run_dir):
    """run.json now, or {} while it is missing or being written."""
    try:
        return json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        return {}


class FlakyExecutor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra", "spark"])
        # An empty exit, then a 500 on the session the first call left behind.
        cls.fakes = fakeadapter.install(
            cls.home, claude=[{"exit": 1, "session": "sid-flaky-1"}, "flaky"],
            codex="work", muse="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.started = time.time()
        proc = cls.home.spawn("run", str(task), "--no-merge")
        cls.waiting = cls.seen = None
        deadline = time.monotonic() + 120
        while cls.waiting is None and proc.poll() is None and time.monotonic() < deadline:
            for run_dir in taskfile.runs(cls.home):
                state = record(run_dir)
                if state.get("transient_wait"):
                    cls.waiting, cls.seen = state, time.time()
            time.sleep(0.1)
        cls.code = proc.wait(timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = record(cls.run_dir)
        cls.log = [re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line)
                   for line in (cls.run_dir / "log.txt").read_text().splitlines()]

    def runs(self, harness):
        return self.fakes[harness].runs()

    def test_the_first_failure_waits_a_minute_and_resumes_the_same_session(self):
        self.assertIn(RETRY, self.log)
        claude = self.runs("claude")
        self.assertEqual([len(call["argv"]) for call in claude], [5, 6])
        self.assertEqual(claude[1]["argv"][5], "sid-flaky-1")
        self.assertEqual([call["role"] for call in claude], ["executor", "executor"])

    def test_while_it_waits_the_record_says_until_when_and_whose_wait_it_is(self):
        self.assertIsNotNone(self.waiting, "run.json never carried transient_wait")
        self.assertEqual(self.waiting["state"], "running")
        wait = self.waiting["transient_wait"]
        self.assertEqual(wait["pid"], self.waiting["pid"])
        # Written between the launch and the moment it was read, a minute ahead of either.
        self.assertGreaterEqual(wait["until"], self.started + 60)
        self.assertLessEqual(wait["until"], self.seen + 60)

    def test_each_attempt_keeps_a_turn_directory_of_its_own(self):
        outs = [Path(call["argv"][4]).relative_to(self.run_dir)
                for harness in ("claude", "codex") for call in self.runs(harness)]
        self.assertEqual(outs, [Path("round-1/executor"), Path("round-1/executor-retry1"),
                                Path("round-1/executor-astra")])
        for out in outs:
            with self.subTest(out):
                self.assertTrue((self.run_dir / out / "prompt.md").is_file())
        self.assertIn("API Error: 500",
                      (self.run_dir / "round-1/executor-retry1/final.md").read_text())

    def test_the_second_failure_in_a_row_hands_the_executor_to_another_provider(self):
        handed = [line for line in self.log if line.startswith("handing executor to")]
        self.assertEqual(len(handed), 1, self.log)
        self.assertTrue(handed[0].startswith("handing executor to astra: opus transient "),
                        handed[0])
        self.assertIn("API Error: 500", handed[0])
        self.assertTrue(handed[0].endswith("(twice in a row)"), handed[0])
        # Retried once only: the third call is the new model's, in a fresh session.
        self.assertEqual(self.fakes["claude"].n, 2)
        codex = self.runs("codex")
        self.assertEqual([(call["role"], len(call["argv"])) for call in codex],
                         [("executor", 5)])
        prompt = (self.run_dir / "round-1/executor-astra/prompt.md").read_text()
        self.assertIn("## Another model started this round", prompt)
        self.assertIn("opus began this round", prompt)
        history = self.state["executor_history"]
        self.assertEqual([{key: entry.get(key) for key in ("from", "to", "model", "rounds", "why")}
                          for entry in history], [
            {"from": "opus", "to": "astra", "model": "opus", "rounds": [1], "why": "transient"}])

    def test_the_reviewer_is_picked_again_so_the_new_executor_never_reviews_itself(self):
        self.assertIn(REPICK, self.log)
        self.assertEqual([call["role"] for call in self.runs("muse")], ["reviewer"])
        self.assertNotIn("reviewer", [call["role"] for call in self.runs("codex")])
        self.assertEqual((self.state["executor"], self.state["reviewer"]), ("astra", "spark"))
        result = (self.run_dir / "result.md").read_text().splitlines()
        self.assertIn("executor: astra   reviewer: spark", result)

    def test_the_run_carries_on_in_the_same_round_and_passes(self):
        self.assertEqual(self.code, 0, self.home.log("spawn-1.err").read_text())
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["round"] for summary in self.state["round_summaries"]], [1])
        handed = next(at for at, line in enumerate(self.log)
                      if line.startswith("handing executor to"))
        order = [self.log.index(RETRY), handed, self.log.index(REPICK),
                 self.log.index("round 1 verdict: PASS")]
        self.assertEqual(order, sorted(order), self.log)
        tree = self.home.run("git", "-C", self.state["worktree"], "ls-tree", "--name-only",
                             "HEAD")
        self.assertIn("retry.txt", tree.out.split())


if __name__ == "__main__":
    unittest.main()
