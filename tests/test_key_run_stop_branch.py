"""`ak run stop` ends a run in flight and takes its branch; `--keep` keeps it to relaunch `from:`.

A stop is how a person calls off work that has gone wrong: the run's turn must end, the record
must say stopped and why, and nothing it cut may be left behind.  When the work so far is worth
keeping, `--keep` leaves the worktree and branch and prints the `from:` line that carries them
into a new task, whose run starts on that branch with the base merged in first and counts as the
same change.  A `from:` naming no branch is refused before any turn.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, a
task from taskfile.py and scripted harnesses from fakeadapter.py whose executor commits and then
holds its turn until the test lets it go.
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


def running(token):
    """The pids of processes whose command line holds `token`: the held turn, seen from the
    host, since a worker's box gives it pids of its own."""
    listing = subprocess.run(["ps", "-A", "-ww", "-o", "pid=", "-o", "args="],
                             capture_output=True, text=True, timeout=30).stdout
    return [int(line.split(None, 1)[0]) for line in listing.splitlines() if token in line]


class Held:
    """A home whose executor commits wip.txt on the run's branch and then holds its turn."""

    def __init__(self, case, title):
        case.home = home = Home()
        case.addClassCleanup(home.close)
        case.rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        case.fakes = fakeadapter.install(home, claude="work", codex="pass")
        self.home, folder = home, case.fakes["claude"].dir
        self.held, self.released = folder / "held", folder / "release"
        case.addClassCleanup(self.release)
        case.fakes["claude"].behave({"write": {"wip.txt": "wip\n"}, "sh": (
            f"git add -A && git commit -qm wip && touch {shlex.quote(str(self.held))} && "
            f"while [ ! -f {shlex.quote(str(self.released))} ]; do sleep 0.1; done")})
        task = taskfile.write(home, case.rig.path, title)
        launched = home.ak("run", str(task), "--no-merge", "--bg")
        assert launched.code == 0, launched.out + launched.err
        self.run_dir = taskfile.only_run(home)
        deadline = time.monotonic() + 120
        while not self.held.exists():
            assert time.monotonic() < deadline, (self.run_dir / "log.txt").read_text()
            time.sleep(0.1)

    def gone(self, bound=30):
        """Whether the held turn has ended, waiting up to `bound` seconds for it to."""
        deadline = time.monotonic() + bound
        while running(str(self.released)) and time.monotonic() < deadline:
            time.sleep(0.1)
        return not running(str(self.released))

    def release(self):
        # Only a failed test leaves the turn held: end whatever of this Home is still going.
        self.released.touch()
        for pid in running(str(self.home.root)):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


class StopRemovesTheBranch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.held = Held(cls, "Add retry file")
        cls.run_id = cls.held.run_dir.name
        cls.done = cls.home.ak("run", "stop", cls.run_id)
        cls.state = json.loads((cls.held.run_dir / "run.json").read_text())

    def test_the_stop_says_the_branch_was_removed_and_the_run_is_stopped_by_the_user(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(self.done.out,
                         f"stopped {self.run_id}: branch ak/add-retry-file removed\n")
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "error")},
                         {"state": "stopped", "verdict": "STOPPED",
                          "error": "stopped by the user"})

    def test_its_worktree_and_branch_are_gone(self):
        self.assertFalse((self.home.path / ".agentkit/wt" / self.run_id).exists())
        self.assertFalse(Path(self.state["worktree"]).exists())
        self.assertEqual(self.rig.branches(remote=False), ["main"])
        self.assertEqual(self.rig.branches(), ["main"])

    def test_result_md_says_stopped_and_why(self):
        lines = (self.held.run_dir / "result.md").read_text().splitlines()
        self.assertEqual(lines[0], "# FAIL — Add retry file")
        self.assertIn("VERDICT: STOPPED", lines)
        why = lines.index("## Why this run stopped")
        self.assertEqual(lines[why + 1:why + 3], ["", "stopped by the user"])

    def test_the_turn_it_was_in_is_ended_too(self):
        self.assertTrue(self.held.gone(), running(str(self.held.released)))
        self.assertFalse(self.held.released.exists())


class StopKeepThenFrom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.held = Held(cls, "Add retry file")
        cls.first = cls.held.run_dir
        cls.stop = cls.home.ak("run", "stop", cls.first.name, "--keep")
        cls.again = cls.home.ak("run", "stop", cls.first.name, "--keep")
        cls.stopped = json.loads((cls.first / "run.json").read_text())
        cls.kept_files = cls.rig.files("ak/add-retry-file", remote=False)
        cls.kept_worktree = Path(cls.stopped["worktree"]).is_dir()
        # main moves on while the work waits: the relaunch must take that in first
        cls.rig.commit({"notes.txt": "notes\n"}, "notes on main")
        saw = cls.fakes["claude"].dir / "saw-both"
        cls.fakes["claude"].behave({**fakeadapter.WORK, "sh": (
            f"test -f wip.txt && test -f notes.txt && touch {shlex.quote(str(saw))}")})
        cls.saw = saw
        task = taskfile.write(cls.home, cls.rig.path, "Finish retry file",
                              front={"from": "ak/add-retry-file"})
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.second = next(run for run in taskfile.runs(cls.home) if run != cls.first)
        cls.state = json.loads((cls.second / "run.json").read_text())

    def test_the_stop_keeps_the_branch_and_prints_the_from_line_to_relaunch_it(self):
        self.assertEqual(self.stop.code, 0, self.stop.out + self.stop.err)
        self.assertEqual(self.stop.out, f"stopped {self.first.name}: branch ak/add-retry-file "
                                        "kept; relaunch with from: ak/add-retry-file\n")
        self.assertEqual({key: self.stopped.get(key) for key in ("state", "verdict", "error")},
                         {"state": "stopped", "verdict": "STOPPED",
                          "error": "stopped by the user"})
        self.assertTrue(self.kept_worktree, self.stopped["worktree"])
        self.assertIn("wip.txt", self.kept_files)
        self.assertTrue(self.held.gone(), running(str(self.held.released)))

    def test_stopping_it_again_says_the_same_and_succeeds(self):
        self.assertEqual(self.again, self.stop)

    def test_a_task_from_the_kept_branch_starts_on_its_work_with_the_base_merged_in_first(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertTrue(self.saw.exists(), "the executor's checkout lacked wip.txt or notes.txt")
        log = (self.second / "log.txt").read_text()
        self.assertIn("from ak/add-retry-file", log)
        self.assertIn("from: merging origin/main", log)
        tree = self.home.run("git", "-C", self.state["worktree"], "ls-tree", "--name-only",
                             "HEAD").out.split()
        self.assertLessEqual({"wip.txt", "notes.txt", "retry.txt"}, set(tree))

    def test_the_relaunch_records_the_branch_it_came_from_and_continues_the_same_change(self):
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "from", "change", "branch")}, {
            "state": "pass", "verdict": "PASS", "from": "ak/add-retry-file",
            "change": self.first.name, "branch": "ak/finish-retry-file"})
        self.assertEqual(self.rig.branches(remote=False),
                         ["ak/add-retry-file", "ak/finish-retry-file", "main"])
        self.assertEqual(self.rig.branches(), ["main"])


class FromMissingBranch(unittest.TestCase):
    def test_a_task_from_a_branch_that_is_not_there_is_refused_before_any_turn(self):
        with Home() as home:
            rig = Rig(home, "widgets")
            akconfig.write(home, ["opus", "astra"])
            fakes = fakeadapter.install(home, claude="work", codex="pass")
            task = taskfile.write(home, rig.path, "Add retry file",
                                  front={"from": "no-such-branch"})
            done = home.ak("run", str(task), "--no-merge")
            self.assertEqual(done.code, 2, done.out + done.err)
            self.assertIn("from: 'no-such-branch' is not a local branch", done.err)
            self.assertEqual((fakes["claude"].n, fakes["codex"].n), (0, 0))
            self.assertEqual(rig.branches(remote=False), ["main"])
            worktrees = home.path / ".agentkit/wt"
            self.assertEqual(list(worktrees.iterdir()) if worktrees.is_dir() else [], [])


if __name__ == "__main__":
    unittest.main()
