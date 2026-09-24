"""Passed runs of one repository take turns from the rebase to the merge.  Entirely offline.

Real throwaway git repos under a temp dir with bare `origin`s; no network, no real harness.
The done-when is a stub that counts its re-checks, and the PR steps are stubs whose merge
squashes the branch into the bare origin the way GitHub would, so the target really moves.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, watch

URL = "https://github.com/fixture/repo/pull/7"

# A run of another process that holds the merge turn until its stdin says to die, and then
# dies without letting go of it: only the kernel does.
HOLDER = """
import os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from agentkit import config, run
config.RUNS = Path(sys.argv[2])
lp = SimpleNamespace(wt=Path(sys.argv[3]), state={"repo": sys.argv[3]}, run_dir=None, log=print)
with run.merge_turn(lp, "origin/main"):
    print("held", flush=True)
    sys.stdin.readline()
    os._exit(1)
"""


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
    run.git(owner, "push", "origin", "main")
    return remote, owner


def make_run(root, remote, name):
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
    return run.Loop(cfg, run_dir, state, {}, log, wt, "body", ["true"], "context", [])


class MergeTurn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".merge-turn-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # `merge` asks only that a `gh` is on PATH; every step that would call it is a stub
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text("#!/bin/sh\nexit 1\n")
        (bin_dir / "gh").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_RUN_ROLE": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.rechecks = {}      # worktree -> the files its re-checks saw
        self.checking = None    # called inside every re-check, when a test wants one
        self.stack.enter_context(patch.object(run, "run_done_when", side_effect=self.recheck))
        self.stack.enter_context(patch.object(run, "rights", return_value=(None, None)))
        self.stack.enter_context(patch.object(run, "open_pr", return_value=URL))
        self.stack.enter_context(patch.object(run, "wait_checks", return_value=True))
        self.stack.enter_context(patch.object(run, "do_merge", side_effect=self.squash))

    def recheck(self, cmds, wt, out, *args, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.rechecks.setdefault(Path(wt), []).append(sorted(p.name for p in Path(wt).glob("*.txt")))
        if self.checking:
            self.checking(Path(wt))
        return True, "$ true\n[exit 0]\n"

    def squash(self, lp, url, upstream):
        """GitHub's squash merge of the pushed branch into main, in the bare origin."""
        owner = Path(run.git(lp.wt, "remote", "get-url", "origin")).parent / "owner"
        run.git(owner, "fetch", "origin")
        run.git(owner, "reset", "--hard", "origin/main")
        run.git(owner, "merge", "--squash", f"origin/{lp.state['branch']}")
        run.git(owner, "commit", "-m", lp.state["title"])
        run.git(owner, "push", "origin", "main")
        lp.state["merged"] = True
        run.save_state(lp.run_dir, lp.state)
        return True

    def land(self, lp, results):
        """`merge` in a thread of its own, as a run's loop would call it."""
        def body():
            try:
                results[lp.state["run_id"]] = run.merge(lp)
            except BaseException as exc:      # the assertion below names it
                results[lp.state["run_id"]] = exc
        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        return thread

    def waiting(self, lp, timeout=20):
        """Poll the run's record until it says it waits for its merge turn."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = run.read_state(lp.run_dir) or {}
            if run.merge_turn_note(state):
                return state
            time.sleep(0.05)
        self.fail(f"{lp.state['run_id']} never waited for its merge turn")

    def test_two_passed_runs_of_one_repo_both_land_with_one_recheck_each(self):
        remote, owner = make_origin(self.root)
        one, two = make_run(self.root, remote, "one"), make_run(self.root, remote, "two")
        commit(owner, "outside.txt", "outside")   # main moved since both were cut
        run.git(owner, "push", "origin", "main")
        inside, release = threading.Event(), threading.Event()

        def hold(wt):
            if wt == one.wt:
                inside.set()
                release.wait(20)
        self.checking = hold
        results = {}
        first = self.land(one, results)
        try:
            self.assertTrue(inside.wait(20), "the first run never reached its re-check")
            second = self.land(two, results)
            state = self.waiting(two)
            # the waiting run is on screen as such, and owns no slot while it waits
            self.assertEqual(run.merge_turn_note(state),
                             f"waiting for the merge turn of {two.wt.name} main")
            self.assertEqual(run.slot_counts({"run_id": "probe"}), (1, 0))
            shown = io.StringIO()
            with redirect_stdout(shown):
                run.cmd_status([])
            self.assertIn(f"waiting for the merge turn of {two.wt.name} main", shown.getvalue())
            self.assertEqual(self.rechecks.get(two.wt), None)    # it has not even rebased
            # nor is it silent: a wait as long as the stall allowance never reads as a stall
            old = time.time() - 3600
            for path in two.run_dir.rglob("*"):
                os.utime(path, (old, old))
            self.assertLess(watch.stall_clock(two.run_dir, {**state, "merge_turn": None}),
                            old + 1)
            self.assertGreater(watch.stall_clock(two.run_dir, state), time.time() - 60)
        finally:
            release.set()
            first.join(60)
        second.join(60)
        self.assertEqual(results, {one.state["run_id"]: True, two.state["run_id"]: True})
        # one re-check each, the second on a main that already carries the first
        self.assertEqual(self.rechecks[one.wt], [["base.txt", "one.txt", "outside.txt"]])
        self.assertEqual(self.rechecks[two.wt],
                         [["base.txt", "one.txt", "outside.txt", "two.txt"]])
        self.assertNotIn("moved to", (two.run_dir / "log.txt").read_text())
        run.git(owner, "pull", "--ff-only", "origin", "main")
        self.assertTrue((owner / "one.txt").exists() and (owner / "two.txt").exists())
        self.assertNotIn("merge_turn", run.read_state(two.run_dir))
        self.assertEqual(run.slot_counts({"run_id": "probe"}), (2, 0))

    def test_one_repository_is_one_turn_however_its_origin_is_spelled(self):
        same = {run.merge_turn_lock(url, "origin/main") for url in (
            "https://github.com/acme/widget.git", "git@github.com:acme/widget.git",
            "ssh://git@github.com:22/acme/widget", "https://github.com/Acme/widget/")}
        self.assertEqual(len(same), 1)
        # spelled alike, yet another repository, or another branch: never the same turn
        self.assertNotEqual(run.merge_turn_lock("https://github.com/acme-one/widget.git",
                                                "origin/main"),
                            run.merge_turn_lock("https://github.com/acme/one-widget.git",
                                                "origin/main"))
        self.assertNotIn(run.merge_turn_lock("https://github.com/acme/widget", "origin/dev"),
                         same)

    def test_a_turn_whose_holder_died_is_taken_over(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "one")
        commit(owner, "outside.txt", "outside")
        run.git(owner, "push", "origin", "main")
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(REPO), str(config.RUNS), str(lp.wt)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.communicate, timeout=20)     # an EOF on stdin ends it too
        self.assertEqual(holder.stdout.readline().strip(), "held")
        results = {}
        thread = self.land(lp, results)
        self.waiting(lp)
        holder.stdin.write("die\n")
        holder.stdin.flush()
        self.assertEqual(holder.wait(20), 1)           # dead, the lock file left behind
        thread.join(60)
        self.assertEqual(results, {lp.state["run_id"]: True})
        self.assertEqual(len(self.rechecks[lp.wt]), 1)
        self.assertIn("took the merge turn", (lp.run_dir / "log.txt").read_text())
        # and the next run finds the dead holder's file, and no wait at all
        again = make_run(self.root, remote, "two")
        commit(owner, "later.txt", "later")
        run.git(owner, "push", "origin", "main")
        self.assertTrue(run.merge(again))
        self.assertNotIn("waiting for the merge turn", (again.run_dir / "log.txt").read_text())

    def test_runs_of_two_repos_integrate_at_the_same_time(self):
        runs = []
        for name in ("alpha", "beta"):
            root = self.root / name
            root.mkdir()
            remote, owner = make_origin(root)
            runs.append(make_run(root, remote, "work"))
            commit(owner, "outside.txt", "outside")
            run.git(owner, "push", "origin", "main")
        both = threading.Barrier(2, timeout=20)
        self.checking = lambda wt: both.wait()      # each re-check waits for the other's
        results = {}
        threads = [self.land(lp, results) for lp in runs]
        for thread in threads:
            thread.join(60)
        self.assertEqual(results, {lp.state["run_id"]: True for lp in runs})
        for lp in runs:
            self.assertEqual(len(self.rechecks[lp.wt]), 1)
            self.assertNotIn("waiting for the merge turn", (lp.run_dir / "log.txt").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
