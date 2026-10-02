"""Passed runs waiting on one repository's merge turn share one suite run.

The run holding the turn stacks the waiting runs' reviewed commits onto its own, runs the
declared suite once on the top, and records the stacked trees; a waiting run whose rebased
commit has one of them lands without running the suite again, and only the tested tree
carries the suite's evidence.  A conflict ends the stack; a failed suite is split to record
the passing prefix, and the failing run and those after it check themselves alone.

Offline: real git commits and queue flocks in an acme sandbox, and the
declared suite run directly in place of the heavy-suite gate.
"""

from contextlib import ExitStack
import fcntl
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
        self.checks, self.lines, self.places = [], [], []
        self.stack.enter_context(patch.object(gate, "run_done_when", side_effect=self.check))
        self.stack.enter_context(patch("os.kill", return_value=None))
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
        """`run_id` holds its queue place at `rank`, without probing any real process."""
        pid = 1000 + rank
        directory = config.RUNS / run_id
        directory.mkdir()
        record.save_state(directory, {
            "run_id": run_id, "state": "running", "merge_method": "squash",
            "pid": pid, "merge_turn": {"pid": pid, "of": "acme main"},
            "review": {"verdict": "PASS", "passed_head_sha": head}})
        turn = run.turn_path(lp, "origin/main")
        place = self.stack.enter_context(
            (turn.parent / f"{turn.stem}.1{rank:020d}-{pid}-1-1.wait").open("w"))
        fcntl.flock(place, fcntl.LOCK_EX)
        place.write("null")
        place.flush()
        self.places.append(place)
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

    def test_a_breaking_follower_leaves_the_leader_tested_alone_in_the_split(self):
        lp = self.leader()
        turn = self.wait(lp, "broken", self.branch("ak/broken", {"broken.txt": "x\n"}), 1)
        self.assertTrue(self.held(lp))
        suites = [cwd for cmds, cwd in self.checks if SUITE in cmds]
        self.assertEqual(len(suites), 2)                         # the batch, then the leader
        self.assertNotIn(self.repo, suites)
        self.assertIn("--- merge: broken breaks the suite of the batch; the 1 run(s) before it "
                      "pass and land", self.lines)
        self.assertEqual(land.passed(turn, self.tree("HEAD"))["tested"], self.tree("HEAD"))
        self.assertEqual(lp.state["final_check"]["tree_sha"], self.tree("HEAD"))

    def test_a_failing_batch_is_halved_and_the_runs_before_the_breaker_land(self):
        lp = self.leader()
        heads = [self.branch(f"ak/m{n}", {f"m{n}.txt": "m\n"}) for n in range(1, 4)]
        heads.insert(2, self.branch("ak/broken", {"broken.txt": "x\n"}))
        for rank, (run_id, head) in enumerate(zip(("m1", "m2", "broken", "m3"), heads), 1):
            turn = self.wait(lp, run_id, head, rank)
        self.assertTrue(self.held(lp))
        suites = [cwd for cmds, cwd in self.checks if SUITE in cmds]
        self.assertEqual(len(suites), 4)        # the batch, then prefixes of 2, 3 and 4
        self.assertNotIn(self.repo, suites)    # the leader passed in the split
        self.assertIn("--- merge: broken breaks the suite of the batch; the 3 run(s) before it "
                      "pass and land", self.lines)
        self.assertIn("final check: the suite on the runs landing together: FAILED; this run "
                      "passed in the split", self.lines)
        first = land.passed(turn, self.tree("HEAD"))
        self.assertEqual(first["leader"], "leader")
        self.assertEqual(len({entry["tested"] for entry in land._trees(turn)[1].values()}), 1)
        self.assertEqual(len(land._trees(turn)[1]), 3)          # leader, m1, m2 -- not broken
        # Each passing member lands without another suite, including the tested prefix top.
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        for run_id in ("m1", "m2"):
            self.git("checkout", "-q", f"ak/{run_id}")
            self.git("rebase", "-q", "origin/main")
            self.checks.clear()
            follower = self.loop(run_id, f"ak/{run_id}")
            self.assertTrue(self.held(follower))
            self.assertEqual([cmds for cmds, _ in self.checks], [["true"]])
            self.assertEqual("suite" in follower.state["final_check"], run_id == "m2")
            self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        # The breaker and the rest of that batch do not form another failing batch.
        self.git("checkout", "-q", "ak/broken")
        self.git("rebase", "-q", "origin/main")
        breaker = self.loop("broken", "ak/broken")
        self.checks.clear()
        with patch.object(run, "target_fails", return_value="red target"), \
                patch.object(run, "park_waiting", return_value=False):
            self.assertFalse(self.held(breaker))
        self.assertEqual([cwd for cmds, cwd in self.checks if SUITE in cmds], [self.repo])
        self.git("checkout", "-q", "ak/m3")
        self.git("rebase", "-q", "origin/main")
        follower = self.loop("m3", "ak/m3")
        self.wait(follower, "fresh", self.branch("ak/fresh", {"fresh.txt": "fresh\n"}), 5)
        self.checks.clear()
        self.assertTrue(self.held(follower))
        self.assertEqual([cwd for cmds, cwd in self.checks if SUITE in cmds], [self.repo])

    def test_a_suite_that_changes_the_stack_cannot_certify_its_committed_tree(self):
        for how in ("dirty", "commit"):
            with self.subTest(how=how):
                lp = self.leader() if how == "dirty" else self.loop()
                if how == "dirty":
                    turn = self.wait(lp, "member", self.branch("ak/member", {"member.txt": "m\n"}), 1)

                def changes(cmds, cwd, *args, **kw):
                    if SUITE in cmds and Path(cwd) != self.repo:
                        (Path(cwd) / "work.txt").write_text("changed\n")
                        if how == "commit":
                            self.git("add", "work.txt", cwd=cwd)
                            self.git("commit", "-q", "-m", "suite changed the tree", cwd=cwd)
                    return self.check(cmds, cwd, *args, **kw)

                with patch.object(gate, "run_done_when", side_effect=changes):
                    self.assertTrue(self.held(lp))
                self.assertEqual(land._trees(turn)[1], {})
                self.assertEqual([cwd for cmds, cwd in self.checks if SUITE in cmds][-1], self.repo)
                self.assertEqual(lp.state["final_check"]["tree_sha"], self.tree("HEAD"))
                self.checks.clear()
                turn.with_suffix(".green").unlink(missing_ok=True)

    def test_an_unlocked_queue_place_is_not_a_live_waiter(self):
        lp = self.leader()
        turn = self.wait(lp, "member", self.branch("ak/member", {"member.txt": "m\n"}), 1)
        place = next(turn.parent.glob(f"{turn.stem}.*.wait"))
        # A stale place must not become live merely because its old pid was reused.
        fcntl.flock(self.places[-1], fcntl.LOCK_UN)
        self.assertEqual(land.waiting(turn), [])
        self.assertTrue(place.exists())

    def test_a_breaking_leader_checks_itself_alone(self):
        self.git("checkout", "-q", "-b", "ak/leader")
        (self.repo / "AGENTS.md").write_text(f"---\ntests: {SUITE}\n---\n")
        (self.repo / "work.txt").write_text("work\n")
        (self.repo / "broken.txt").write_text("x\n")
        self.commit("leader")
        lp = self.loop()
        turn = self.wait(lp, "m1", self.branch("ak/m1", {"m1.txt": "m\n"}), 1)
        self.assertFalse(self.held(lp))
        self.assertIn("--- merge: leader breaks the suite of the batch; it is the first, so each "
                      "run checks itself alone", self.lines)
        self.assertEqual(land._trees(turn)[1], {})

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
