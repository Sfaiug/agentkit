"""Passed runs of one repository verify on their own and take turns only to land.  Offline.

Real throwaway git repos under a temp dir with bare `origin`s; no network, no real harness.
The done-when is a stub that counts its re-checks, the fixer and reviewer are stubs, and the
PR steps are stubs whose merge squashes the branch into the bare origin the way GitHub would,
so the target really moves.  The merge turn is the real one, watched: a re-check or a fixer
turn taken while its own run holds the turn is recorded, and none may be.
"""

from contextlib import ExitStack, contextmanager, redirect_stdout
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


def make_run(root, remote, name, edits=None):
    """A passed run of `remote` on ak/<name>, its record in the runs directory.

    Its work is `<name>.txt`, and whatever `edits` writes besides.
    """
    wt = root / name
    run.git(root, "clone", str(remote), str(wt))
    run.git(wt, "config", "user.name", "fixture")
    run.git(wt, "config", "user.email", "fixture@localhost")
    run.git(wt, "checkout", "-b", f"ak/{name}")
    for path, text in (edits or {}).items():
        (wt / path).write_text(text)
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
        self.failing = set()    # worktrees whose next re-check fails
        self.fixer = None       # a fixer turn, when a test expects one
        self.landing = None     # called inside the required checks, holding the turn
        self.queuing = None     # called as a verified run queues for its turn
        self.events = []        # (what, worktree), in the order they happened
        self.holding = set()    # the worktrees whose run holds its merge turn now
        self.inside = []        # re-checks and fixer turns taken while their run held it
        real_turn = run.merge_turn

        @contextmanager
        def turn(lp, upstream, *args, **kwargs):
            if self.queuing:
                self.queuing(lp)
            with real_turn(lp, upstream, *args, **kwargs):
                self.events.append(("turn", lp.wt))
                self.holding.add(lp.wt)
                try:
                    yield
                finally:
                    self.holding.discard(lp.wt)
        self.stack.enter_context(patch.object(run, "merge_turn", turn))
        self.stack.enter_context(patch.object(run, "run_done_when", side_effect=self.recheck))
        self.stack.enter_context(patch.object(run, "execute", side_effect=self.fix))
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=self.reviewer))
        self.stack.enter_context(patch.object(run, "rights", return_value=(None, None)))
        self.stack.enter_context(patch.object(run, "open_pr", return_value=URL))
        self.stack.enter_context(patch.object(run, "wait_checks", side_effect=self.required))
        self.stack.enter_context(patch.object(run, "do_merge", side_effect=self.squash))

    def recheck(self, cmds, wt, out, *args, **kwargs):
        wt = Path(wt)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.rechecks.setdefault(wt, []).append(sorted(p.name for p in wt.glob("*.txt")))
        self.events.append(("recheck", wt))
        if wt in self.holding:
            self.inside.append(("recheck", wt))
        if self.checking:
            self.checking(wt)
        if wt in self.failing:
            self.failing.discard(wt)
            return False, "$ true\n[exit 1]\n"
        return True, "$ true\n[exit 0]\n"

    def fix(self, lp, role, text, name):
        if lp.wt in self.holding:
            self.inside.append(("fixer", lp.wt))
        if not self.fixer:
            raise AssertionError(f"unexpected {name} turn in {lp.wt.name}")
        return self.fixer(lp)

    def reviewer(self, cfg, name, body, workspace, out, *args, **kwargs):
        answer = "VERDICT: PASS\n\n## Findings\n- none\n"
        out.mkdir(parents=True)
        (out / "final.md").write_text(answer)
        return 0, answer, None, False

    def required(self, lp, url):
        """The PR's required checks: a moment, unless a test holds a run in them."""
        self.events.append(("checks", lp.wt))
        if self.landing:
            self.landing(lp)
        return True

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

    def test_a_failing_recheck_and_its_fixer_hold_no_turn_while_another_run_lands(self):
        remote, owner = make_origin(self.root)
        one, two = make_run(self.root, remote, "one"), make_run(self.root, remote, "two")
        commit(owner, "outside.txt", "outside")   # main moved since both were cut
        run.git(owner, "push", "origin", "main")
        self.failing.add(one.wt)                  # the first run's re-check on it fails
        fixing, release = threading.Event(), threading.Event()

        def fixer(lp):
            fixing.set()
            release.wait(20)
            return "## Summary\nFixed."
        self.fixer = fixer
        results = {}
        first = self.land(one, results)
        try:
            self.assertTrue(fixing.wait(20), "the first run never reached its fixer round")
            self.land(two, results).join(60)
            # the second landed whole while the first sat in its fixer round, never waiting
            self.assertEqual(results, {two.state["run_id"]: True})
            self.assertNotIn("waiting for the merge turn", (two.run_dir / "log.txt").read_text())
        finally:
            release.set()
            first.join(60)
        self.assertEqual(results, {one.state["run_id"]: True, two.state["run_id"]: True})
        self.assertEqual(self.inside, [])
        # the failing re-check, the fixer's, and one on the main the second landed on
        self.assertEqual(self.rechecks[one.wt], [["base.txt", "one.txt", "outside.txt"]] * 2
                         + [["base.txt", "one.txt", "outside.txt", "two.txt"]])
        self.assertIn("fixer opus (findings after the rebase of origin/main)",
                      (one.run_dir / "log.txt").read_text())
        run.git(owner, "pull", "--ff-only", "origin", "main")
        self.assertTrue((owner / "one.txt").exists() and (owner / "two.txt").exists())

    def test_an_unchanged_target_lands_directly(self):
        remote, owner = make_origin(self.root)
        lp = make_run(self.root, remote, "one")
        commit(owner, "outside.txt", "outside")   # verified on, and still there to land on
        run.git(owner, "push", "origin", "main")
        self.assertTrue(run.merge(lp))
        self.assertEqual(self.events, [("recheck", lp.wt), ("turn", lp.wt), ("checks", lp.wt)])
        self.assertNotIn(" moved ", (lp.run_dir / "log.txt").read_text())
        state = run.read_state(lp.run_dir)
        self.assertEqual(run.git(lp.wt, "rev-parse", f"origin/{state['branch']}"),
                         state["review"]["head_sha"])       # the commit re-checked is the one pushed
        self.assertEqual(state["delivery_sha"], state["review"]["head_sha"])

    def test_a_queued_run_lands_on_a_disjoint_move_without_a_recheck(self):
        remote, owner = make_origin(self.root)
        one, two = make_run(self.root, remote, "one"), make_run(self.root, remote, "two")
        commit(owner, "outside.txt", "outside")   # main moved since both were cut
        run.git(owner, "push", "origin", "main")
        inside, release = threading.Event(), threading.Event()

        def hold(lp):
            if lp is one:
                inside.set()
                release.wait(20)
        self.landing = hold                       # the first run sits in its required checks
        results = {}
        first = self.land(one, results)
        try:
            self.assertTrue(inside.wait(20), "the first run never reached its required checks")
            second = self.land(two, results)
            state = self.waiting(two)
            # it verified before it queued, on the main the first has not landed on yet
            self.assertEqual(self.rechecks[two.wt], [["base.txt", "outside.txt", "two.txt"]])
            verified = run.git(two.wt, "rev-parse", "HEAD")
            # the waiting run is on screen as such, and owns no slot while it waits
            self.assertEqual(run.merge_turn_note(state),
                             f"waiting for the merge turn of {two.wt.name} main")
            self.assertEqual(run.slot_counts({"run_id": "probe"}), (1, 0))
            shown = io.StringIO()
            with redirect_stdout(shown):
                run.cmd_status([])
            self.assertIn(f"waiting for the merge turn of {two.wt.name} main", shown.getvalue())
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
        self.assertEqual(self.inside, [])
        # one re-check each: the first's move touched only one.txt, so the second lands on it
        self.assertEqual(self.rechecks[one.wt], [["base.txt", "one.txt", "outside.txt"]])
        self.assertEqual(self.rechecks[two.wt], [["base.txt", "outside.txt", "two.txt"]])
        self.assertIn("--- merge: origin/main moved 1 commits, none touching this branch's files; "
                      "landing on the verified checks", (two.run_dir / "log.txt").read_text())
        state = run.read_state(two.run_dir)
        self.assertEqual(state["review"]["rebased_from"], verified)
        self.assertEqual(state["delivery_sha"], state["review"]["head_sha"])
        run.git(owner, "pull", "--ff-only", "origin", "main")
        self.assertTrue((owner / "one.txt").exists() and (owner / "two.txt").exists())
        self.assertNotIn("merge_turn", state)
        self.assertEqual(run.slot_counts({"run_id": "probe"}), (2, 0))

    def overlapping(self, owner, *lines):
        """A `queuing` that sets main's last line of shared.txt to the next of `lines` each time."""
        remaining = list(lines)

        def move(lp):
            if remaining:
                (owner / "shared.txt").write_text(f"1\n2\n3\n4\n{remaining.pop(0)}\n")
                run.git(owner, "commit", "-am", "main edits shared")
                run.git(owner, "push", "origin", "main")
        return move

    def test_an_overlapping_move_verifies_again_outside_the_turn(self):
        remote, owner = make_origin(self.root)
        commit(owner, "shared.txt", "1\n2\n3\n4\n5")
        run.git(owner, "push", "origin", "main")
        lp = make_run(self.root, remote, "one", {"shared.txt": "one\n2\n3\n4\n5\n"})
        commit(owner, "outside.txt", "outside")   # so every lap has a rebase to re-check
        run.git(owner, "push", "origin", "main")
        self.queuing = self.overlapping(owner, "five")   # main edits the branch's file meanwhile
        self.assertTrue(run.merge(lp))
        self.assertEqual(self.inside, [])
        self.assertEqual(self.events, [("recheck", lp.wt), ("turn", lp.wt),
                                       ("recheck", lp.wt), ("turn", lp.wt), ("checks", lp.wt)])
        log = (lp.run_dir / "log.txt").read_text()
        self.assertIn("touching this branch's files; verifying again outside the merge turn", log)
        self.assertNotIn("none touching", log)
        run.git(owner, "pull", "--ff-only", "origin", "main")
        self.assertEqual((owner / "shared.txt").read_text(), "one\n2\n3\n4\nfive\n")

    def test_three_overlapping_moves_park_waiting(self):
        remote, owner = make_origin(self.root)
        commit(owner, "shared.txt", "1\n2\n3\n4\n5")
        run.git(owner, "push", "origin", "main")
        lp = make_run(self.root, remote, "one", {"shared.txt": "one\n2\n3\n4\n5\n"})
        commit(owner, "outside.txt", "outside")   # so every lap has a rebase to re-check
        run.git(owner, "push", "origin", "main")
        self.queuing = self.overlapping(owner, "5a", "5b", "5c")
        self.assertFalse(run.merge(lp))
        self.assertEqual(self.inside, [])
        self.assertEqual(self.events, [("recheck", lp.wt), ("turn", lp.wt)] * 3)
        state = run.read_state(lp.run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["waiting_on"]["ref"], "origin/main")
        self.assertIn("moved three times", state["merge_note"])
        self.assertNotIn("merge_turn", state)

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
        self.assertEqual(len(self.rechecks[lp.wt]), 1)          # verified before it queued
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
