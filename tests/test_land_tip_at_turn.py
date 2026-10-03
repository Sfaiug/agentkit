"""The lander checks a member on the target tip, and a changed tree rejoins.

Offline: real throwaway git repos under a temp dir with a bare `origin`, fake
done-when commands that record what they saw, and a temporary HOME. No network,
no real harness: a clean integration keeps its review, so no fixer or reviewer
runs except where a test installs a stub.
"""

from contextlib import ExitStack, contextmanager
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.landing import landing
from agentkit import gate, host, config, run, worker
from agentkit import record


def commit(cwd, name, message):
    (cwd / name).write_text(f"{message}\n")
    run.git(cwd, "add", ".")
    run.git(cwd, "commit", "-m", message)


def make_origin(root):
    """A bare origin and an owner clone that moves it, standing in for GitHub."""
    remote = root / "origin.git"
    run.git(root, "init", "--bare", "--initial-branch=main", str(remote))
    owner = root / "owner"
    run.git(root, "clone", str(remote), str(owner))
    run.git(owner, "config", "user.name", "fixture")
    run.git(owner, "config", "user.email", "fixture@localhost")
    commit(owner, "base.txt", "base")
    commit(owner, "tip.txt", "tip-one")
    run.git(owner, "push", "origin", "main")
    return remote, owner


def make_run(root, remote, name, cmds):
    """A passed run of `remote` on ak/<name>, its record in the runs directory."""
    wt = root / name
    run.git(root, "clone", str(remote), str(wt))
    run.git(wt, "config", "user.name", "fixture")
    run.git(wt, "config", "user.email", "fixture@localhost")
    run.git(wt, "checkout", "-b", f"ak/{name}")
    commit(wt, f"{name}.txt", name)
    run_dir = config.RUNS / f"{root.name}-{name}"
    run_dir.mkdir(parents=True)
    (run_dir / "log.txt").touch()
    head = run.git(wt, "rev-parse", "HEAD")
    tree = run.git(wt, "rev-parse", "HEAD^{tree}")
    cfg = config.load()
    executor_provider, reviewer_provider = run.review_providers(cfg, "opus", "astra")

    def log(msg):
        with (run_dir / "log.txt").open("a") as fh:
            fh.write(f"[00:00:00] {msg}\n")

    state = {
        "run_id": run_dir.name, "title": name, "state": "running", "verdict": "PASS",
        **record.process_owner(), "started_at": time.time(),
        "review": {"executor": "opus", "executor_provider": executor_provider,
                   "reviewer": "astra", "reviewer_provider": reviewer_provider,
                   "returncode": 0, "verdict": "PASS", "done_when": True,
                   "head_sha": head, "tree_sha": tree},
        "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                             "summary": "work", "head_sha": head, "tree_sha": tree}],
        "rounds": 3, "base": "origin/main", "target": "origin/main",
        "base_sha": run.git(wt, "rev-parse", "origin/main^{commit}"), "branch": f"ak/{name}",
        "worktree": str(wt), "repo": str(wt), "executor": "opus", "reviewer": "astra",
        "merge_method": "squash", "merged": False, "merge_failed": False,
        "merge_note": None, "findings": "",
    }
    record.save_state(run_dir, state)
    return run.Loop(cfg, run_dir, state, {}, log, wt, "body", cmds, "context", [])


class LandTipAtTurn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-land-tip-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # the suites' AK_MAX_RUNS=0 takes no gate turn at all; these laps must take one
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        os.environ.pop("AK_MAX_RUNS", None)
        self.stack.enter_context(patch.object(gate, "GATE_POLL", 0.05))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.05))
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 1\n")
        self.counter = self.root / "counter"
        self.counter.touch()
        self.pickups = []
        self.stack.enter_context(patch.object(
            run, "pickup_new_code",
            side_effect=lambda lp, **kw: self.pickups.append(kw.get("extra")) or False))
        self.stack.enter_context(patch.object(
            run, "execute", side_effect=AssertionError("unexpected fixer turn")))
        self.stack.enter_context(patch.object(
            run, "call_retrying", side_effect=AssertionError("unexpected reviewer turn")))

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def test_target_moving_while_suite_waits_rejoins_then_checks_the_delivered_tree(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "acme",
                      [f"echo \"every $(git rev-parse HEAD) $(cat tip.txt)\" >> {self.counter}",
                       f"echo \"once $(git rev-parse HEAD)\" >> {self.counter}  # once"])
        repo = run.main_checkout(lp.state["repo"])
        holder = gate.gate_lock(repo, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        results = {}
        waiting = threading.Event()
        real_gate = gate.gate_turn

        @contextmanager
        def gate_wait(*args, **kwargs):
            waiting.set()
            with real_gate(*args, **kwargs):
                yield

        self.stack.enter_context(patch.object(gate, "gate_turn", side_effect=gate_wait))

        def body():
            try:
                results["landed"] = landing(lp, lambda: True)
            except BaseException as exc:      # noqa: BLE001 -- the test reads it
                results["landed"] = exc

        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        try:
            self.until(waiting.is_set,
                       "the lander to wait for a heavy turn")
            self.assertEqual(self.counter.read_text(), "")
            # A disjoint target move still changes the commit the suite must check.
            commit(owner, "tip.txt", "tip-two")
            run.git(owner, "push", "origin", "main")
            tip_two = run.git(owner, "rev-parse", "main^{commit}")
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
        thread.join(60)
        self.assertFalse(thread.is_alive(), "the landing never finished")
        self.assertEqual(results["landed"], False)
        self.assertTrue(landing(lp, lambda: True))
        head = run.git(lp.wt, "rev-parse", "HEAD")
        rc, _ = run.git_out(lp.wt, "merge-base", "--is-ancestor", tip_two, "HEAD")
        self.assertEqual(rc, 0)
        rows = [line.split() for line in self.counter.read_text().splitlines()]
        self.assertEqual([row[0] for row in rows], ["every", "once", "every", "once"])
        self.assertEqual(rows[0][2], "tip-one")   # the scratch checkout was pinned before the move
        self.assertEqual(lp.state["final_check"]["tree_sha"],
                         run.git(lp.wt, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(lp.state["final_check"]["sha"], head)
        self.assertEqual(self.pickups, [])

    def test_a_passing_member_runs_each_command_once(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "widget",
                      [f"echo \"every $(git rev-parse HEAD) $(cat tip.txt)\" >> {self.counter}",
                       f"echo \"once $(git rev-parse HEAD)\" >> {self.counter}  # once"])
        commit(owner, "tip.txt", "tip-two")     # the target moved since the branch was cut
        run.git(owner, "push", "origin", "main")
        landed = landing(lp, lambda: True)
        self.assertTrue(landed)
        self.assertEqual(self.pickups, [])
        head = run.git(lp.wt, "rev-parse", "HEAD")
        rows = [line.split() for line in self.counter.read_text().splitlines()]
        self.assertEqual([row[0] for row in rows], ["every", "once"])
        self.assertEqual(len(rows[0][1]), 40)
        self.assertEqual(rows[0][2], "tip-two")
        self.assertEqual(rows[1][1], rows[0][1])
        self.assertEqual(lp.state["final_check"]["tree_sha"],
                         run.git(lp.wt, "rev-parse", "HEAD^{tree}"))

    def test_a_conflict_frees_the_gate_turn_before_the_fixer_starts(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "gizmo", ["true"])
        (lp.wt / "shared.txt").write_text("branch side\n")
        run.git(lp.wt, "add", ".")
        run.git(lp.wt, "commit", "-m", "branch shared")
        (owner / "shared.txt").write_text("target side\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "target shared")
        run.git(owner, "push", "origin", "main")
        # the saved review covers the branch head, so the lap reaches the rebase itself
        head = run.git(lp.wt, "rev-parse", "HEAD")
        tree = run.git(lp.wt, "rev-parse", "HEAD^{tree}")
        state = record.read_state(lp.run_dir)
        state["review"].update(head_sha=head, tree_sha=tree)
        state["round_summaries"][-1].update(head_sha=head, tree_sha=tree)
        record.save_state(lp.run_dir, state)
        lp.state = state
        repo = run.main_checkout(lp.state["repo"])
        seen = {}

        def fixer(lp, role, text, name):
            conflicts = run.git(lp.wt, "diff", "--name-only", "--diff-filter=U",
                                check=False).splitlines()
            seen["conflicted"] = [p for p in conflicts if p]
            seen["held"] = getattr(gate._GATE_HELD, "hold", None)
            try:
                with gate.gate_lock(repo, 0).open("a") as slot:
                    fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(slot, fcntl.LOCK_UN)
                seen["free"] = True
            except BlockingIOError:
                seen["free"] = False
            return "## Summary\nDid nothing."

        with patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "resume_review", return_value="FAIL"):
            landed = landing(lp, lambda: True)
        self.assertFalse(landed)
        self.assertEqual(seen.get("conflicted"), ["shared.txt"])
        self.assertIsNone(seen.get("held"))
        self.assertTrue(seen.get("free"))
        state = record.read_state(lp.run_dir)
        self.assertNotIn("waiting_on", state)
        self.assertIn("did not finish", state["merge_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
