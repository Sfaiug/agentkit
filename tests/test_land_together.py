"""Passed runs waiting on one repository's merge turn share one suite run.

The run holding the turn stacks the waiting runs' reviewed commits onto its own, runs the
declared suite once on the top, and records the stacked trees; a waiting run whose rebased
commit has one of them lands without running the suite again, and only the tested tree
carries the suite's evidence.  A conflict ends the stack; a failed suite records nothing and
the holder checks itself alone.

Offline: real git commits in an acme sandbox, live `sleep` processes as the waiters, and the
declared suite run directly in place of the heavy-suite gate.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, land, run
from agentkit import record

SUITE = "test -f work.txt && test ! -f broken.txt"


class LandTogether(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-land-together-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Land test")
        self.git("config", "user.email", "land@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.checks, self.lines = [], []
        self.stack.enter_context(patch.object(gate, "run_done_when", side_effect=self.check))
        self.addCleanup(lambda: hasattr(run._MERGE_HELD, "hold") and delattr(run._MERGE_HELD,
                                                                                "hold"))

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)

    def check(self, cmds, cwd, log_path, *args, **_kw):
        self.checks.append((list(cmds), Path(cwd)))
        results = [subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True)
                   for cmd in cmds]
        ok = all(result.returncode == 0 for result in results)
        text = "$ " + "\n$ ".join(cmds) + f"\n[exit {0 if ok else 1}]\n"
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(text)
        return ok, text

    def branch(self, name, files):
        """A branch from the base with these files, checked out back on the leader after."""
        here = self.git("rev-parse", "--abbrev-ref", "HEAD")
        self.git("checkout", "-q", "-b", name, self.base)
        for path, text in files.items():
            (self.repo / path).write_text(text)
        self.commit(name)
        head = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", here)
        return head

    def loop(self, run_id="leader", branch="ak/leader"):
        state = {"run_id": run_id, "title": run_id, "state": "running", "verdict": "PASS",
                 "executor": "opus", "reviewer": "astra",
                 "review": {"executor": "opus", "executor_provider": "anthropic",
                            "reviewer": "astra", "reviewer_provider": "openai",
                            "returncode": 0, "verdict": "PASS", "done_when": True},
                 "round_summaries": [], "rounds": 1,
                 "base": "origin/main", "target": "main", "base_sha": self.base,
                 "branch": branch, "worktree": str(self.repo), "repo": str(self.repo),
                 "merge_method": "squash", "merged": False, "findings": ""}
        directory = config.RUNS / run_id
        directory.mkdir(exist_ok=True)
        record.save_state(directory, state)
        lp = run.Loop(self.cfg, directory, state, {}, self.lines.append, self.repo, "",
                      ["true", f"{SUITE}  # once"], "", [])
        lp.state["review"].update(run.commit_identity(self.repo))
        return lp

    def leader(self):
        self.git("checkout", "-q", "-b", "ak/leader")
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {SUITE}\n---\n")
        (self.repo / "work.txt").write_text("work\n")
        self.commit("leader")
        return self.loop()

    def wait(self, lp, run_id, head, rank):
        """`run_id` waits for lp's merge turn behind a live process, at `rank` in the queue."""
        sleeper = subprocess.Popen(["sleep", "120"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        directory = config.RUNS / run_id
        directory.mkdir()
        record.save_state(directory, {
            "run_id": run_id, "state": "running", "merge_method": "squash",
            "merge_turn": {"pid": sleeper.pid, "of": "acme main"},
            "review": {"verdict": "PASS", "passed_head_sha": head}})
        turn = run.turn_path(lp, "origin/main")
        (turn.parent / f"{turn.stem}.1{rank:020d}-{sleeper.pid}-1-1.wait").write_text("null")
        return turn

    def tree(self, rev, cwd=None):
        return self.git("rev-parse", f"{rev}^{{tree}}", cwd=cwd)

    def held(self, lp):
        run._MERGE_HELD.hold = object()
        try:
            return run.final_check(lp, "origin/main")
        finally:
            del run._MERGE_HELD.hold

    def test_the_holder_checks_the_queue_once_and_each_tree_lands_without_the_suite(self):
        lp = self.leader()
        member = self.branch("ak/member", {"member.txt": "member\n"})
        clash = self.branch("ak/clash", {"work.txt": "clash\n"})
        later = self.branch("ak/later", {"later.txt": "later\n"})
        self.wait(lp, "member", member, 1)
        self.wait(lp, "clash", clash, 2)
        turn = self.wait(lp, "later", later, 3)
        self.assertTrue(self.held(lp))
        suites = [cwd for cmds, cwd in self.checks if SUITE in cmds]
        self.assertEqual(len(suites), 1)                       # one suite run, not on its own
        self.assertNotEqual(suites[0], self.repo)
        self.assertIn("--- merge: landing together: 2 runs on origin/main: leader, member",
                      self.lines)
        self.assertIn("--- merge: clash does not stack on the batch; it lands on its own turn",
                      self.lines)
        self.assertIn("final check: the suite on the runs landing together: all passed",
                      self.lines)
        self.assertIsNone(land.passed(turn, self.tree(later)))   # nothing past the conflict
        mine = land.passed(turn, self.tree("HEAD"))
        self.assertEqual(mine["leader"], "leader")
        self.assertNotEqual(mine["tested"], self.tree("HEAD"))
        self.assertEqual(lp.state["final_check"]["together"], "leader")
        self.assertNotIn("suite", lp.state["final_check"])      # its own tree was not tested
        # the leader merges; the member rebases onto it and lands the tested tree
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        self.git("checkout", "-q", "ak/member")
        self.git("rebase", "-q", "origin/main")
        self.assertEqual(self.tree("HEAD"), mine["tested"])
        self.checks.clear()
        follower = self.loop("member", "ak/member")
        self.assertTrue(run.final_check(follower, "origin/main"))
        self.assertEqual([cmds for cmds, _ in self.checks], [["true"]])   # no suite again
        self.assertIn("final check: the suite already passed on this tree with leader; "
                      "not running it again", self.lines)
        self.assertEqual(follower.state["final_check"]["suite"], SUITE)
        self.assertEqual(follower.state["final_check"]["tree_sha"], mine["tested"])

    def test_a_failing_batch_records_nothing_and_the_holder_checks_itself(self):
        lp = self.leader()
        turn = self.wait(lp, "broken", self.branch("ak/broken", {"broken.txt": "x\n"}), 1)
        self.assertTrue(self.held(lp))
        suites = [cwd for cmds, cwd in self.checks if SUITE in cmds]
        self.assertEqual(len(suites), 2)
        self.assertEqual(suites[-1], self.repo)                  # alone, on its own commit
        self.assertIn("final check: the suite on the runs landing together: FAILED; "
                      "checking this run alone", self.lines)
        self.assertIsNone(land.passed(turn, self.tree("HEAD")))
        self.assertEqual(lp.state["final_check"]["tree_sha"], self.tree("HEAD"))

    def test_alone_or_not_holding_the_turn_it_checks_itself_as_before(self):
        lp = self.leader()
        self.assertTrue(self.held(lp))
        self.assertEqual([cwd for cmds, cwd in self.checks if SUITE in cmds], [self.repo])
        self.assertFalse(any("landing together" in line for line in self.lines))
        self.checks.clear()
        lp.state.pop("final_check")
        self.wait(lp, "member", self.branch("ak/member", {"member.txt": "m\n"}), 1)
        self.assertTrue(run.final_check(lp, "origin/main"))       # no turn held: no batch
        self.assertEqual([cwd for cmds, cwd in self.checks if SUITE in cmds], [self.repo])

    def test_a_recorded_tree_is_forgotten_after_a_day(self):
        turn = config.RUNS / ".merge-x.lock"
        land.note(turn, ["a", "b"], "leader")
        self.assertEqual(land.passed(turn, "a")["tested"], "b")
        with patch.object(land.time, "time", return_value=time.time() + land.KEEP + 1):
            self.assertIsNone(land.passed(turn, "a"))


if __name__ == "__main__":
    unittest.main()
