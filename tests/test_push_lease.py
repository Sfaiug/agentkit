"""A passed run pushes its branch even when a merged PR used the name before.  Entirely offline.

Real throwaway git repos under a temp dir with a bare `origin`.  GitHub deletes a merged
PR's branch on origin, but a fetch that does not prune keeps the clone's tracking ref at
the old head, and `push --force-with-lease` then refused the next run with that name as
if another run had taken it (run 20260924-0634).  A name origin really carries under a
commit this run never pushed is still refused, whether it arrived before integration's
fetch or during the push; one origin took from this run stays its own, even unrecorded.
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
from test_merge_step import make_loop, make_repos


class PushLease(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".push-lease-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        config.ensure_dirs()
        _, self.owner, self.wt = make_repos(self.root)

    def test_a_name_a_merged_pr_used_pushes(self):
        # the earlier run pushed ak/test and merged; GitHub deleted the branch on origin
        run.git(self.wt, "push", "origin", "ak/test")
        run.git(self.owner, "push", "origin", "--delete", "ak/test")
        self.assertTrue(run.git(self.wt, "rev-parse", "--verify", "--quiet",
                                "refs/remotes/origin/ak/test", check=False))
        # this run reuses the name for work of its own
        run.git(self.wt, "reset", "--hard", "origin/main")
        (self.wt / "later.txt").write_text("later\n")
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-m", "later work")
        lp, _, _ = make_loop(self.root, self.wt)
        self.assertTrue(run.integrate(lp, "origin/main"))
        self.assertTrue(run.push(lp), lp.state.get("merge_note"))
        self.assertEqual(self.on_origin(), run.git(self.wt, "rev-parse", "HEAD"))

    def test_a_push_origin_took_before_it_stopped_stays_ours(self):
        lp, run_dir, _ = make_loop(self.root, self.wt)
        del lp.state["delivery_sha"]            # the fixture's; this run has pushed nothing yet
        self.assertTrue(run.integrate(lp, "origin/main"))
        real = run.git_out

        def stopped_after(cwd, *args):
            answer = real(cwd, *args)
            if args[0] == "push":
                raise run.Stopped("killed after origin took the push")
            return answer

        with patch.object(run, "git_out", side_effect=stopped_after), \
                self.assertRaises(run.Stopped):
            run.push(lp)
        pushed = self.on_origin()
        # the retry reads the run back and rebases onto a target that moved meanwhile
        (self.owner / "moved.txt").write_text("moved\n")
        run.git(self.owner, "add", ".")
        run.git(self.owner, "commit", "-m", "main moved")
        run.git(self.owner, "push", "origin", "main")
        lp.state = run.read_state(run_dir)

        def checks(cmds, wt, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            return True, "$ true\n[exit 0]\n"

        with patch.object(run, "run_done_when", side_effect=checks):
            self.assertTrue(run.integrate(lp, "origin/main"))
        self.assertNotEqual(run.git(self.wt, "rev-parse", "HEAD"), pushed)
        self.assertTrue(run.push(lp), lp.state.get("merge_note"))
        self.assertEqual(self.on_origin(), run.git(self.wt, "rev-parse", "HEAD"))

    def on_origin(self):
        return run.git(self.owner, "ls-remote", "origin", "refs/heads/ak/test").split()[0]

    def take(self):
        """Another run pushes the same name with work of its own."""
        run.git(self.owner, "checkout", "-b", "ak/test")
        (self.owner / "other.txt").write_text("other\n")
        run.git(self.owner, "add", ".")
        run.git(self.owner, "commit", "-m", "other run")
        run.git(self.owner, "push", "origin", "ak/test")

    def refused(self, lp):
        self.assertFalse(run.push(lp))
        self.assertIn("taken by another run", lp.state["merge_note"])
        self.assertEqual(self.on_origin(), run.git(self.owner, "rev-parse", "HEAD"))

    def test_a_name_taken_before_integration_is_refused(self):
        # the fetch adopts the other run's commit as the tracking ref, so a lease on that
        # ref alone would let this push replace it
        lp, _, _ = make_loop(self.root, self.wt)
        self.take()
        self.assertTrue(run.integrate(lp, "origin/main"))
        self.refused(lp)

    def test_a_name_taken_during_the_push_is_refused(self):
        lp, _, _ = make_loop(self.root, self.wt)
        self.assertTrue(run.integrate(lp, "origin/main"))
        real = run.git_out

        def racing(cwd, *args):
            if args[0] == "push":
                # another run pushes the name, and a fetch in another worktree records it
                self.take()
                real(cwd, "fetch", "origin")
            return real(cwd, *args)

        with patch.object(run, "git_out", side_effect=racing):
            self.refused(lp)

if __name__ == "__main__":
    unittest.main()
