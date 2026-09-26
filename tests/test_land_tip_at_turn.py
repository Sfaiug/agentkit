"""A landing lap takes the target's tip once it holds its gate turn, and checks once.

Offline: real throwaway git repos under a temp dir with a bare `origin`, fake
done-when commands that record what they saw, and a temporary HOME. No network,
no real harness: a clean integration keeps its review, so no fixer or reviewer
runs except where a test installs a stub.
"""

from contextlib import ExitStack
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
from agentkit import config, run, worker


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
        **run.process_owner(), "started_at": time.time(),
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
    run.save_state(run_dir, state)
    return run.Loop(cfg, run_dir, state, {}, log, wt, "body", cmds, "context", [])


class LandTipAtTurn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".land-tip-", dir=REPO)
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
        self.stack.enter_context(patch.object(run, "GATE_POLL", 0.05))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.05))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
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

    def test_a_move_during_the_wait_is_taken_in_after_the_turn_is_held(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "acme",
                      [f"echo \"every $(git rev-parse HEAD) $(cat tip.txt)\" >> {self.counter}",
                       f"echo \"once $(git rev-parse HEAD)\" >> {self.counter}  # once"])
        repo = run.main_checkout(lp.state["repo"])
        holder = run.gate_lock(repo, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        results = {}

        def body():
            try:
                results["landed"] = run.land(
                    lp, "origin/main",
                    lambda: run.integrate(lp, "origin/main")
                    and run.final_check(lp, "origin/main"), lambda: True,
                    execv=lambda *a: self.fail("no pickup here"))
            except BaseException as exc:      # noqa: BLE001 -- the test reads it
                results["landed"] = exc

        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        try:
            self.until(lambda: (run.read_state(lp.run_dir) or {}).get("gate_turn"),
                       "the lander to mark its gate wait")
            # the target moves while the lander waits: the tip it rebases onto
            # cannot be older than this move
            commit(owner, "tip.txt", "tip-two")
            run.git(owner, "push", "origin", "main")
            tip_two = run.git(owner, "rev-parse", "main^{commit}")
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
        thread.join(60)
        self.assertFalse(thread.is_alive(), "the landing never finished")
        self.assertEqual(results["landed"], True)
        log = (lp.run_dir / "log.txt").read_text()
        self.assertIn(f"rebasing ak/acme onto origin/main ({tip_two[:12]})", log)
        head = run.git(lp.wt, "rev-parse", "HEAD")
        rc, _ = run.git_out(lp.wt, "merge-base", "--is-ancestor", tip_two, "HEAD")
        self.assertEqual(rc, 0)
        every = [line.split() for line in self.counter.read_text().splitlines()
                 if line.startswith("every ")]
        self.assertEqual(len(every), 1)
        self.assertEqual(every[0][1], head)         # the check ran on the rebased commit
        self.assertEqual(every[0][2], "tip-two")    # which carries the new tip
        self.assertFalse((lp.run_dir / "landing-turn.log").exists())

    def test_a_passing_lap_runs_each_command_once(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "widget",
                      [f"echo \"every $(git rev-parse HEAD) $(cat tip.txt)\" >> {self.counter}",
                       f"echo \"once $(git rev-parse HEAD)\" >> {self.counter}  # once"])
        commit(owner, "tip.txt", "tip-two")     # the target moved since the branch was cut
        run.git(owner, "push", "origin", "main")
        landed = run.land(lp, "origin/main",
                          lambda: run.integrate(lp, "origin/main")
                          and run.final_check(lp, "origin/main"), lambda: True,
                          execv=lambda *a: self.fail("no pickup here"))
        self.assertTrue(landed)
        self.assertEqual(self.pickups, [{"land_lap": 1}])
        head = run.git(lp.wt, "rev-parse", "HEAD")
        rows = [line.split() for line in self.counter.read_text().splitlines()]
        self.assertEqual([row[0] for row in rows], ["every", "once"])
        self.assertEqual(rows[0][1], head)
        self.assertEqual(rows[0][2], "tip-two")
        self.assertEqual(rows[1][1], head)
        log = (lp.run_dir / "log.txt").read_text()
        self.assertIn("done-when passed again, review kept", log)
        self.assertIn("final check: 1 commands (1 once)", log)
        self.assertIn("final check: all passed", log)

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
        state = run.read_state(lp.run_dir)
        state["review"].update(head_sha=head, tree_sha=tree)
        state["round_summaries"][-1].update(head_sha=head, tree_sha=tree)
        run.save_state(lp.run_dir, state)
        lp.state = state
        repo = run.main_checkout(lp.state["repo"])
        seen = {}

        def fixer(lp, role, text, name):
            conflicts = run.git(lp.wt, "diff", "--name-only", "--diff-filter=U",
                                check=False).splitlines()
            seen["conflicted"] = [p for p in conflicts if p]
            seen["held"] = getattr(run._GATE_HELD, "hold", None)
            try:
                with run.gate_lock(repo, 0).open("a") as slot:
                    fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(slot, fcntl.LOCK_UN)
                seen["free"] = True
            except BlockingIOError:
                seen["free"] = False
            return "## Summary\nDid nothing."

        with patch.object(run, "execute", side_effect=fixer):
            landed = run.land(lp, "origin/main",
                              lambda: run.integrate(lp, "origin/main")
                              and run.final_check(lp, "origin/main"), lambda: True,
                              execv=lambda *a: self.fail("no pickup here"))
        self.assertFalse(landed)
        self.assertEqual(seen.get("conflicted"), ["shared.txt"])
        self.assertIsNone(seen.get("held"))
        self.assertTrue(seen.get("free"))
        state = run.read_state(lp.run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertIn("did not finish", state["merge_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
