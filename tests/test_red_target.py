"""A landing check that fails on the target itself parks, spending no fixer round.

Real throwaway git repos under a temp dir with a bare `origin`; no network, no real
harness.  The gates are real fake done-when commands whose pass or fail depends on which
commit is checked out, the fixer only removes the branch's own breakage, and the
reviewer always passes.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run


def make_repos(root):
    """A bare origin, an owner clone that moves it, and a work clone on ak/fix-api."""
    remote = root / "origin.git"
    run.git(root, "init", "--bare", "--initial-branch=main", str(remote))
    owner = root / "owner"
    run.git(root, "clone", str(remote), str(owner))
    for cwd in (owner,):
        run.git(cwd, "config", "user.name", "fixture")
        run.git(cwd, "config", "user.email", "fixture@localhost")
    (owner / "base.txt").write_text("base\n")
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", "base")
    run.git(owner, "push", "origin", "main")
    wt = root / "wt"
    run.git(root, "clone", str(remote), str(wt))
    run.git(wt, "config", "user.name", "fixture")
    run.git(wt, "config", "user.email", "fixture@localhost")
    run.git(wt, "checkout", "-b", "ak/fix-api")
    (wt / "work.txt").write_text("work\n")
    run.git(wt, "add", ".")
    run.git(wt, "commit", "-m", "work")
    return remote, owner, wt


def make_loop(root, wt, cmds, rounds=3, spent=1, cfg=None):
    """A run that passed review on its last recorded round, `spent` of `rounds`."""
    run_dir = root / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "log.txt").touch()
    (run_dir / f"round-{spent}").mkdir(parents=True, exist_ok=True)
    head = run.git(wt, "rev-parse", "HEAD")
    tree = run.git(wt, "rev-parse", "HEAD^{tree}")
    base_sha = run.git(wt, "rev-parse", "origin/main^{commit}")
    lines = []

    def log(msg):
        line = f"[00:00:00] {msg}"
        lines.append(line)
        print(line, flush=True)
        with (run_dir / "log.txt").open("a") as fh:
            fh.write(line + "\n")

    cfg = cfg or config.load()
    executor_provider, reviewer_provider = run.review_providers(cfg, "opus", "astra")
    state = {
        "run_id": "red-target-test", "title": "red target", "state": "running",
        "verdict": "PASS",
        "review": {"executor": "opus", "executor_provider": executor_provider, "reviewer": "astra",
                   "reviewer_provider": reviewer_provider, "returncode": 0, "verdict": "PASS",
                   "done_when": True, "head_sha": head, "tree_sha": tree},
        "round_summaries": [{"round": n, "verdict": "PASS", "done_when": True,
                             "summary": "work", "head_sha": head, "tree_sha": tree}
                            for n in range(1, spent + 1)],
        "rounds": rounds, "base": "origin/main", "target": "origin/main",
        "base_sha": base_sha, "branch": "ak/fix-api", "worktree": str(wt),
        "repo": str(wt), "executor": "opus", "reviewer": "astra",
        "merge_method": "squash", "merged": False, "merge_failed": False,
        "merge_note": None, "findings": "", "delivery_sha": head,
    }
    run.save_state(run_dir, state)
    lp = run.Loop(cfg, run_dir, state, {}, log, wt, "body", cmds, "context", [])
    return lp, run_dir, lines


class RedTarget(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".red-target-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.turns, self.reviews = [], []
        self.stack.enter_context(patch.object(run, "execute", side_effect=self.fixer))
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=self.review_call))

    def fixer(self, lp, role, text, name):
        self.turns.append(name)
        # the branch's own breakage, and nothing else: whatever the target carries
        # is not this fixer's to touch
        if (lp.wt / "breakage").exists():
            (lp.wt / "breakage").unlink()
            run.git(lp.wt, "add", "-A")
            run.git(lp.wt, "commit", "-m", "remove the branch's breakage")
        return "## Summary\nRemoved the breakage."

    def review_call(self, cfg, name, body, workspace, out, role, session, log, limit=None):
        self.reviews.append(role)
        self.assertEqual(role, "reviewer")
        answer = "VERDICT: PASS\n\n## Findings\n- none\n"
        out.mkdir(parents=True)
        (out / "final.md").write_text(answer)
        return 0, answer, session, False

    def assert_on_branch_head_and_clean(self, wt, head):
        self.assertEqual(run.git(wt, "rev-parse", "HEAD"), head)
        self.assertEqual(run.git(wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual(run.git(wt, "status", "--porcelain"), "")
        self.assertEqual(run.git_out(wt, "diff", "--quiet", "HEAD")[0], 0)

    def test_final_check_failing_on_the_target_parks_waiting_without_a_fixer(self):
        # `false` fails wherever it runs: the branch did not break it, the target is
        # red, and no fixer round is spent finding that out twice
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, ["true", "false  # once"])
        head = run.git(wt, "rev-parse", "HEAD")
        self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, [])
        self.assertEqual(self.reviews, [])
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["verdict"], "PASS")
        self.assertFalse(state["merge_failed"])
        self.assertEqual(state["merge_note"], "origin/main itself fails: `false`")
        self.assertEqual(state["waiting_on"], {"ref": "origin/main",
                                               "sha": run.git(owner, "rev-parse", "HEAD")})
        self.assertEqual(state["final_check"]["outcome"], "failed")
        self.assertIn("$ false (on origin/main", (run_dir / "target-probe.log").read_text())
        self.assert_on_branch_head_and_clean(wt, head)

    def test_final_check_passing_on_the_target_runs_the_fixer(self):
        # the branch carries a breakage the target never had: the probe passes there,
        # so the fixer runs exactly as today and the run lands through
        _, _, wt = make_repos(self.root)
        (wt / "breakage").write_text("branch only\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch breakage")
        lp, run_dir, _ = make_loop(self.root, wt, ["true", "test ! -f breakage  # once"])
        self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, ["final-fixer"])
        state = run.read_state(run_dir)
        self.assertEqual(state["final_check"]["outcome"], "passed")
        self.assertTrue(run.current_review(lp))
        self.assertIn("$ test ! -f breakage (on origin/main",
                      (run_dir / "target-probe.log").read_text())

    def test_either_probe_leaves_the_worktree_on_the_branch_head_and_clean(self):
        # the red-target probe puts the worktree back exactly; the passing probe leaves
        # it on the branch head the fixer's own commit moved, clean either way
        _, _, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, ["true", "false  # once"])
        head = run.git(wt, "rev-parse", "HEAD")
        self.assertFalse(run.final_check(lp, "origin/main"))
        self.assert_on_branch_head_and_clean(wt, head)
        (wt / "breakage").write_text("branch only\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch breakage")
        lp, run_dir, _ = make_loop(self.root, wt, ["true", "test ! -f breakage  # once"])
        self.assertTrue(run.final_check(lp, "origin/main"))
        fixed = run.git(wt, "rev-parse", "HEAD")
        self.assertNotEqual(fixed, head)
        self.assert_on_branch_head_and_clean(wt, fixed)

    def test_probe_droppings_colliding_with_the_branch_still_restore_it(self):
        # the probe regenerates `gen`, which the branch tracks and the tip does not: the
        # droppings are dropped before the checkout back, so they cannot block it and
        # the worktree is back on the branch head, clean, with the branch file intact
        _, _, wt = make_repos(self.root)
        (wt / "gen").write_text("branch generated\n")
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-m", "branch generated file")
        lp, run_dir, _ = make_loop(self.root, wt, ["true", "touch gen && false  # once"])
        head = run.git(wt, "rev-parse", "HEAD")
        self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(self.turns, [])
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["merge_note"],
                         "origin/main itself fails: `touch gen && false`")
        self.assert_on_branch_head_and_clean(wt, head)
        self.assertEqual((wt / "gen").read_text(), "branch generated\n")

    def test_stopped_restore_step_still_puts_the_branch_back(self):
        # a git killed mid-restore raises Stopped even with `check=False`: the other
        # half still runs, the stop still ends the probe, and the branch is back
        _, _, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, ["true", "false  # once"])
        head = run.git(wt, "rev-parse", "HEAD")
        real_git = run.git
        calls = []

        def stopping_git(repo, *args, **kwargs):
            calls.append(args)
            if args[:1] == ("reset",):
                raise run.Stopped("fixture stop")
            return real_git(repo, *args, **kwargs)

        with patch.object(run, "git", side_effect=stopping_git):
            with self.assertRaises(run.Stopped):
                run.target_fails(lp, "origin/main", "$ false\n[exit 1]\n")
        self.assertIn(("checkout", "--quiet", "ak/fix-api"), calls)
        self.assert_on_branch_head_and_clean(wt, head)

    def test_integration_recheck_failing_on_the_target_parks_without_a_fixer(self):
        # the target moved under a poison the branch took in on a clean rebase: the
        # re-check fails on the target's own tip too, so no review and no fixer run
        _, owner, wt = make_repos(self.root)
        (owner / "poison").write_text("target only\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "poison on the target")
        run.git(owner, "push", "origin", "main")
        tip = run.git(owner, "rev-parse", "HEAD")
        lp, run_dir, _ = make_loop(self.root, wt, ["test ! -f poison"])
        self.assertFalse(run.integrate(lp, "origin/main"))
        self.assertEqual(self.turns, [])
        self.assertEqual(self.reviews, [])
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertNotEqual(state["verdict"], "FAIL")
        self.assertFalse(state["merge_failed"])
        self.assertEqual(state["merge_note"],
                         "origin/main itself fails: `test ! -f poison`")
        self.assertEqual(state["waiting_on"], {"ref": "origin/main", "sha": tip})
        # the rebase invalidated the review before the re-check ran, as in every
        # integrate park: the retry re-reviews once the target moves
        self.assertIn("review_pending", state)
        self.assertTrue(run.integrated(wt, tip))
        self.assertEqual(run.git(wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual(run.git(wt, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
