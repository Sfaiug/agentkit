"""A run that lost a landing lap holds the merge turn through its next lap.

Offline: real throwaway git repos under a temp dir with a bare `origin`, fake
done-when commands that record what they saw, and a temporary HOME. No network,
no real harness: a clean integration keeps its review, so no fixer or reviewer
runs except where a test installs a stub. The PR steps are stubs whose merge
squashes the branch into the bare origin the way GitHub would, so the target
really moves. The merge turn is the real one, probed with a non-blocking flock.
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
from agentkit import config, run

URL = "https://github.com/fixture/repo/pull/7"


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
    (owner / "shared.txt").write_text("1\n2\n3\n4\n5\n")
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", "shared")
    run.git(owner, "push", "origin", "main")
    return remote, owner


def make_run(root, remote, name, cmds, edits=None):
    """A passed run of `remote` on ak/<name>, its record in the runs directory."""
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
    return run.Loop(cfg, run_dir, state, {}, log, wt, "body", cmds, "context", [])


def merge_held(wt):
    """Whether this host's merge turn for `wt`'s origin is held now, by any thread."""
    url = run.git(wt, "remote", "get-url", "origin")
    path = run.merge_turn_lock(url, "origin/main")
    with path.open("a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False


class LandReserve(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".land-reserve-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
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
        self.counter = self.root / "counter"
        self.counter.touch()
        self.pickups = []
        self.stack.enter_context(patch.object(
            run, "pickup_new_code",
            side_effect=lambda lp, **kw: self.pickups.append(
                (lp.state["run_id"], kw.get("extra"))) or False))
        self.queuing = None
        self.checks = []      # (worktree name, held at the check) in order
        self.rebases = []     # (worktree name, held at the rebase) in order
        self.merges = []      # (worktree name, held at the merge) in order
        self.fixer_seen = {}
        self.fixer = None
        real_turn = run.merge_turn
        real_done_when = run.run_done_when
        real_git_out = run.git_out

        @contextmanager
        def turn(lp, upstream, *args, **kwargs):
            if self.queuing:
                self.queuing(lp)
            with real_turn(lp, upstream, *args, **kwargs):
                yield
        self.stack.enter_context(patch.object(run, "merge_turn", turn))

        def done_when(cmds, wt, out, *args, **kwargs):
            own = getattr(run._MERGE_HELD, "hold", None) is not None
            self.checks.append((Path(wt).name, own))
            return real_done_when(cmds, wt, out, *args, **kwargs)
        self.stack.enter_context(patch.object(run, "run_done_when", side_effect=done_when))

        def git_out(repo, *args):
            if args[:1] == ("rebase",):
                own = getattr(run._MERGE_HELD, "hold", None) is not None
                self.rebases.append((Path(repo).name, own))
            return real_git_out(repo, *args)
        self.stack.enter_context(patch.object(run, "git_out", side_effect=git_out))

        def fix(lp, role, text, name):
            self.fixer_seen["held"] = merge_held(lp.wt)
            self.fixer_seen["own"] = getattr(run._MERGE_HELD, "hold", None) is not None
            self.fixer_seen["note"] = run.merge_turn_note(run.read_state(lp.run_dir) or {})
            if not self.fixer:
                raise AssertionError(f"unexpected {name} turn in {lp.wt.name}")
            return self.fixer(lp)
        self.stack.enter_context(patch.object(run, "execute", side_effect=fix))

        def reviewer(cfg, name, body, workspace, out, *args, **kwargs):
            answer = "VERDICT: PASS\n\n## Findings\n- none\n"
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, None, False
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=reviewer))
        self.stack.enter_context(patch.object(run, "rights", return_value=(None, None)))
        self.stack.enter_context(patch.object(run, "open_pr", return_value=URL))
        self.stack.enter_context(patch.object(run, "wait_checks", return_value=True))
        self.stack.enter_context(patch.object(run, "do_merge", side_effect=self.squash))

    def squash(self, lp, url, upstream):
        """GitHub's squash merge of the pushed branch into main, in the bare origin."""
        own = getattr(run._MERGE_HELD, "hold", None) is not None
        self.merges.append((lp.wt.name, own))
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
        def body():
            try:
                results[lp.state["run_id"]] = run.merge(lp)
            except BaseException as exc:      # the assertion below names it
                results[lp.state["run_id"]] = exc
        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        return thread

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def test_second_lap_holds_from_before_its_rebase_until_its_merge(self):
        remote, owner = make_origin(self.root)
        slow = (f"sleep 2; echo acme $(git rev-parse HEAD) >> {self.counter}")
        fast = f"echo bravo $(git rev-parse HEAD) >> {self.counter}"
        one = make_run(self.root, remote, "acme", [slow],
                       {"shared.txt": "acme\n2\n3\n4\n5\n"})
        two = make_run(self.root, remote, "bravo", [fast])
        (owner / "shared.txt").write_text("1\n2\n3\n4\noutside\n")
        run.git(owner, "commit", "-am", "main moves first")
        run.git(owner, "push", "origin", "main")
        moved = []

        def overlapping(lp):
            if not moved and lp.wt.name == "acme":
                moved.append(True)
                (owner / "shared.txt").write_text("1\n2\n3\n4\nfive\n")
                run.git(owner, "commit", "-am", "main edits shared")
                run.git(owner, "push", "origin", "main")
        self.queuing = overlapping
        results = {}
        first = self.land(one, results)
        try:
            self.until(lambda: run.merge_turn_note(run.read_state(one.run_dir) or {}).startswith(
                "holding the merge turn"), "the second lap to hold the turn")
            holding_note = run.merge_turn_note(run.read_state(one.run_dir) or {})
            self.assertEqual(holding_note, "holding the merge turn of acme main to land")
            second = self.land(two, results)
            second.join(60)
            self.assertFalse(second.is_alive(), "the second run never finished")
        finally:
            first.join(60)
        self.assertFalse(first.is_alive(), "the reserved run never finished")
        self.assertEqual(results.get(one.state["run_id"]), True)
        self.assertEqual(results.get(two.state["run_id"]), True)
        laps = [extra for run_id, extra in self.pickups if run_id == one.state["run_id"]]
        self.assertEqual(laps, [{"land_lap": 1}, {"land_lap": 2}])
        acme_checks = [held for name, held in self.checks if name == "acme"]
        self.assertEqual(acme_checks, [False, True])
        acme_rebases = [held for name, held in self.rebases if name == "acme"]
        self.assertEqual(acme_rebases, [False, True])
        acme_merges = [held for name, held in self.merges if name == "acme"]
        self.assertEqual(acme_merges, [True])
        bravo_checks = [held for name, held in self.checks if name == "bravo"]
        self.assertEqual(bravo_checks, [False])
        self.assertIn("waiting for the merge turn", (two.run_dir / "log.txt").read_text())
        run.git(owner, "pull", "--ff-only", "origin", "main")
        self.assertTrue((owner / "acme.txt").exists() and (owner / "bravo.txt").exists())

    def test_failing_check_in_reserved_lap_frees_before_fixer(self):
        remote, owner = make_origin(self.root)
        gate = self.root / "gate"
        gate.write_text("0")
        # the first check passes, the second fails twice (a single failure only
        # earns the flaky re-run), and every check after the fixer passes
        cmd = (f"lines=$(cat {gate}); echo $((lines + 1)) > {gate}; "
               f"echo lap$((lines + 1)) >> {self.counter}; "
               "test \"$lines\" != 1 -a \"$lines\" != 2")
        lp = make_run(self.root, remote, "acme", [cmd],
                      {"shared.txt": "acme\n2\n3\n4\n5\n"})
        (owner / "shared.txt").write_text("1\n2\n3\n4\noutside\n")
        run.git(owner, "commit", "-am", "main moves first")
        run.git(owner, "push", "origin", "main")
        moved = []

        def overlapping(run_lp):
            if not moved:
                moved.append(True)
                (owner / "shared.txt").write_text("1\n2\n3\n4\nfive\n")
                run.git(owner, "commit", "-am", "main edits shared")
                run.git(owner, "push", "origin", "main")
        self.queuing = overlapping

        def fixed(lp):
            lp.round_dir.mkdir(parents=True, exist_ok=True)
            return "## Summary\nFixed."
        self.fixer = fixed
        self.assertTrue(run.merge(lp))
        laps = [extra for run_id, extra in self.pickups if run_id == lp.state["run_id"]]
        self.assertEqual(laps, [{"land_lap": 1}, {"land_lap": 2}])
        acme_checks = [held for name, held in self.checks if name == "acme"]
        self.assertEqual(acme_checks[:2], [False, True])
        self.assertIn("held", self.fixer_seen)
        self.assertFalse(self.fixer_seen["held"])
        self.assertFalse(self.fixer_seen["own"])
        self.assertEqual(self.fixer_seen["note"], "")

    def test_first_lap_and_disjoint_landing_never_take_early(self):
        remote, owner = make_origin(self.root)
        direct = make_run(self.root, remote, "acme",
                           [f"echo acme $(git rev-parse HEAD) >> {self.counter}"])
        (owner / "outside.txt").write_text("outside\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "outside")
        run.git(owner, "push", "origin", "main")
        self.assertTrue(run.merge(direct))
        self.assertEqual([extra for _, extra in self.pickups], [{"land_lap": 1}])
        self.assertEqual([held for name, held in self.checks if name == "acme"], [False])
        self.assertEqual([held for name, held in self.rebases if name == "acme"], [False])
        disjoint = make_run(self.root, remote, "bravo",
                             [f"echo bravo $(git rev-parse HEAD) >> {self.counter}"])
        (owner / "later.txt").write_text("later\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "later")
        run.git(owner, "push", "origin", "main")

        def outside(lp):
            if lp.wt.name == "bravo":
                (owner / "arrival.txt").write_text("arrival\n")
                run.git(owner, "add", ".")
                run.git(owner, "commit", "-m", "arrival")
                run.git(owner, "push", "origin", "main")
                self.queuing = None
        self.queuing = outside
        self.assertTrue(run.merge(disjoint))
        self.assertIn("none touching this branch's files",
                      (disjoint.run_dir / "log.txt").read_text())
        self.assertEqual([held for name, held in self.checks if name == "bravo"], [False])
        # the first rebase is the lap's verify, outside the turn; the second is the
        # disjoint move itself, rebased onto under the turn to land
        self.assertEqual([held for name, held in self.rebases if name == "bravo"],
                         [False, True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
