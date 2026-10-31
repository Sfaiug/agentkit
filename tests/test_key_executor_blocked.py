"""An executor's blocked ends its run unreviewed and undelivered; not-needed ends only a fix run.

`ak hand-in blocked "why"` is how a worker says the task cannot be done as written: the run
stops there, BLOCKED with that reason, with no reviewer or fixer turn spent on it and nothing
pushed or opened, even when the turn committed work.  `ak hand-in not-needed "why"` is for a
fix run's first turn, a run ak starts for a review follow-up once its run merged: it ends that
run `not_needed`, with no review or PR, leaving no branch or checkout behind.  In any other
turn ak takes it as done, and the checks and the review go on.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py
with the GitHub of fakegh.py, a seat from akseat.py and scripted harnesses from fakeadapter.py.
"""

import json
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

WHY = "cannot be done as written"
# Work committed before the hand-in: blocked must still deliver none of it.
BLOCKED = {**fakeadapter.WORK, "final": "Blocked.", "hand_in": [["blocked", WHY]]}
NOT_NEEDED = {"final": "Not needed.", "hand_in": [["not-needed", "already done"]]}
FOLLOW_UP = {"final": "One for later.", "hand_in": [
    ["follow-up", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
     "test ! -f retry.txt"], ["done"]]}


def state(run_dir):
    return json.loads((run_dir / "run.json").read_text())


class ExecutorBlocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.base = cls.rig.head()
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")      # a pass would be pushed and merged
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=BLOCKED, codex="pass")
        cls.seat = Seat(cls.home, "acme", cwd=cls.rig.path, planned=True) if REAL_TMUX else None
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), env=cls.seat and {"AGENTKIT_SESSION": "acme"}, timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = state(cls.run_dir)

    def test_the_run_ends_blocked_with_the_executor_s_reason_and_exits_1(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual([hand_in["code"] for hand_in in self.fakes["claude"].runs()[0]
                          ["hand_ins"]], [0])
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "merged", "pr", "round_summaries")}, {
            "state": "blocked", "verdict": "BLOCKED", "merged": False, "pr": None,
            "round_summaries": []})
        logged = (self.run_dir / "log.txt").read_text().splitlines()
        self.assertTrue([line for line in logged if line.endswith(f"] BLOCKED {WHY}")], logged)
        # Blocked delivers nothing, so the foreground's last line is a failed delivery.
        self.assertTrue(self.done.out.rstrip("\n").endswith(
            f"FAIL -> {self.run_dir / 'result.md'}"), self.done.out)

    def test_no_reviewer_or_fixer_turn_follows_and_nothing_is_pushed_or_opened(self):
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 0))
        self.assertEqual(self.gh.prs(), [])
        self.assertFalse([call for call in self.home.calls("gh") if call[:1] == ["pr"]])
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.rig.head(), self.base)
        # The turn's commit stays on the run's own branch, where the owner can look at it.
        self.assertEqual(self.rig.git("rev-parse", "ak/add-retry-file^"), self.base)

    def test_result_md_says_blocked_and_why(self):
        lines = (self.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# BLOCKED — Add retry file")
        for line in ("VERDICT: BLOCKED", "rounds: 0 of 3", "pr: (none)", "merged: no"):
            self.assertIn(line, lines)
        after = lines[lines.index("## Blocked") + 1:]
        self.assertEqual(next(line for line in after if line.strip()), WHY)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_its_seat_is_told_in_one_line_to_rewrite_the_task(self):
        self.assertRegex(self.seat.wait_lines(1)[0], rf"^run {self.run_dir.name} BLOCKED \(0 of 3\): {WHY}\. Next: "
                         r"rewrite the task and relaunch it with `from: ak/add-retry-file`\. Result: \S+/result\.md$")


class NotNeededOutsideAFixRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=NOT_NEEDED, codex="pass")
        # A check that already holds, so only the hand-in could end the run early.
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file",
                              done_when=("test -f .keep",))
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)

    def test_not_needed_closes_the_turn_as_done_and_the_review_goes_on(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([hand_in["code"] for hand_in in self.fakes["claude"].runs()[0]
                          ["hand_ins"]], [0])
        record = state(self.run_dir)
        self.assertEqual((record["state"], record["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["verdict"] for summary in record["round_summaries"]],
                         ["PASS"])
        self.assertEqual([run["role"] for run in self.fakes["codex"].runs()], ["reviewer"])
        self.assertEqual(self.rig.head("ak/add-retry-file", remote=False), self.rig.head())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NotNeededInAFixRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.gh = GitHub(cls.home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=["work", NOT_NEEDED],
                                        codex=[FOLLOW_UP, "pass"])
        # Only a seat's merged run starts a fix run for each of its review follow-ups.
        Seat(cls.home, "acme", cwd=cls.rig.path, record={"workers": ["opus", "astra"]},
             planned=True)
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"},
                               timeout=300)
        others = [run for run in taskfile.runs(cls.home)
                  if not run.name.endswith("-add-retry-file")]
        cls.fix = others[0] if len(others) == 1 else None
        cls.last = cls.ended(cls.fix) if cls.fix else None

    @staticmethod
    def ended(run_dir, bound=120):
        """The fix run is detached: it has ended once its log's last line names its result."""
        deadline = time.monotonic() + bound
        while time.monotonic() < deadline:
            try:
                last = (run_dir / "log.txt").read_text().rstrip("\n").rsplit("\n", 1)[-1]
            except FileNotFoundError:
                last = ""
            if last.endswith(f" -> {run_dir / 'result.md'}"):
                return last
            time.sleep(0.2)
        raise AssertionError(f"{run_dir.name} never ended: {state(run_dir).get('state')}")

    def setUp(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertIsNotNone(self.fix, [run.name for run in taskfile.runs(self.home)])

    def test_the_fix_run_ends_not_needed_with_its_reason_and_no_review(self):
        record = state(self.fix)
        self.assertEqual({key: record.get(key) for key in (
            "state", "verdict", "merged", "pr", "round_summaries")}, {
            "state": "not_needed", "verdict": None, "merged": False, "pr": None,
            "round_summaries": []})
        self.assertRegex(self.last, r"\] not needed: already done -> ")
        turn = self.fakes["claude"].runs()[1]
        self.assertEqual((turn["role"], [hand_in["code"] for hand_in in turn["hand_ins"]]),
                         ("executor", [0]))
        # The one review is the merged run's: the fix run asked no reviewer.
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (2, 1))

    def test_it_pushes_and_opens_nothing_and_leaves_no_branch_or_checkout(self):
        record = state(self.fix)
        self.assertEqual([pr["number"] for pr in self.gh.prs()], [1])
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.rig.head(), self.gh.pr(1)["merge"]["commit"])
        self.assertNotIn(record["branch"], self.rig.branches(remote=False))
        self.assertFalse((self.home.path / ".agentkit/wt" / self.fix.name).exists())
        self.assertFalse(Path(record["worktree"]).exists())

    def test_result_md_says_not_needed_and_why(self):
        lines = (self.fix / "result.md").read_text().splitlines()
        self.assertTrue(lines[0].startswith("# not needed: already done — Fix "), lines[0])
        for line in ("rounds: 0 of 3", "pr: (none)", "merged: no"):
            self.assertIn(line, lines)


if __name__ == "__main__":
    unittest.main()
