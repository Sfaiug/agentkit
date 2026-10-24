"""A branch merged onto its target keeps the target's lines first, as a rebase would.

A union-merged file (ATLAS's `migrations/ORDER`) reads the target's new lines before the
branch's, whether the run integrates by merge or the lander stacks it, and a merge that
conflicts still stops in progress for the conflict handling.  Offline: throwaway repos.
"""

from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_merge_step as fixture
from agentkit import config, gitcall, land, roundloop, run


def commit(cwd, message, **files):
    for name, text in files.items():
        (cwd / name).write_text(text)
    run.git(cwd, "add", ".")
    run.git(cwd, "commit", "-m", message)


class TargetLinesFirst(unittest.TestCase):
    review_call = fixture.MergeStep.review_call

    def setUp(self):
        fixture.MergeStep.setUp(self)
        self.stack.enter_context(patch.object(config, "WT", self.root / "scratch"))
        config.WT.mkdir()
        _, self.owner, self.wt = fixture.make_repos(self.root)
        commit(self.owner, "union ORDER", **{".gitattributes": "ORDER merge=union\n",
                                             "ORDER": "old\n"})
        run.git(self.owner, "push", "origin", "main")
        run.git(self.wt, "fetch", "origin")
        run.git(self.wt, "merge", "--no-edit", "origin/main")    # the branch carries a merge
        commit(self.wt, "branch line", ORDER="old\nb\n")
        self.head = run.git(self.wt, "rev-parse", "HEAD")

    def advance(self, text):
        commit(self.owner, "target line", ORDER=text)
        run.git(self.owner, "push", "origin", "main")
        run.git(self.wt, "fetch", "origin")
        return run.git(self.wt, "rev-parse", "origin/main")

    def loop(self):
        lp, _, _ = fixture.make_loop(self.root, self.wt)
        lp.state["base_sha"] = run.git(self.wt, "merge-base", self.head, "origin/main")
        self.assertEqual(roundloop.how_to_integrate(lp), "merge")
        return lp

    def stacked(self, tip, opened):
        state = {"review": {"head_sha": self.head}, "merge_method": "squash",
                 "base_sha": run.git(self.wt, "merge-base", self.head, tip)}
        return land._stack_member(self.wt, state, tip, "origin/main", opened)

    def test_merged_union_lines_read_the_targets_first(self):
        tip = self.advance("old\nm\n")
        with ExitStack() as opened:
            scratch, text = self.stacked(tip, opened)
            self.assertFalse(text)
            stacked = run.git(scratch, "rev-parse", "HEAD^{tree}")
            self.assertEqual((scratch / "ORDER").read_text(), "old\nm\nb\n")
        self.assertTrue(run.integrate(self.loop(), "origin/main"))
        self.assertEqual((self.wt / "ORDER").read_text(), "old\nm\nb\n")
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD^{tree}"), stacked)
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD^1", "HEAD^2").split(), [self.head, tip])
        self.assertEqual(run.git(self.wt, "status", "--porcelain"), "")

    def test_a_conflicting_merge_stops_in_progress(self):
        commit(self.wt, "branch shared", shared="branch\n")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        commit(self.owner, "target shared", shared="target\n")
        tip = self.advance("old\nm\n")
        with ExitStack() as opened:
            scratch, text = self.stacked(tip, opened)
            self.assertIn("ERROR: merge of origin/main failed", text)
            self.assertTrue(roundloop.in_progress(scratch, "merge"))
        seen = []

        def resolve(lp, upstream, out, how, pinned):
            seen.append((how, pinned, roundloop.in_progress(self.wt, "merge")))
            return False

        with patch.object(roundloop, "resolve_conflicts", side_effect=resolve):
            self.assertFalse(run.integrate(self.loop(), "origin/main"))
        self.assertEqual(seen, [("merge", tip, True)])

    def test_git_merge_still_makes_the_commit(self):
        # its hooks and signing apply as to any merge: a hook refusing it keeps the head
        tip = self.advance("old\nm\n")
        hook = self.wt / ".git" / "hooks" / "pre-merge-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assertNotEqual(gitcall.merge(self.wt, tip)[0], 0)
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), self.head)

    def test_staged_work_is_refused_as_git_refuses_it(self):
        tip = self.advance("old\nm\n")
        (self.wt / "work.txt").write_text("staged\n")
        run.git(self.wt, "add", "work.txt")
        self.assertNotEqual(gitcall.merge(self.wt, tip)[0], 0)
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), self.head)
        self.assertEqual(run.git(self.wt, "show", ":work.txt"), "staged")


if __name__ == "__main__":
    unittest.main()
