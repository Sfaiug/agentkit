"""A closed unmerged pull request's branch on origin goes when collection removes its run's
worktree, and stays whenever any condition does not hold.

The dry run asks neither GitHub nor origin and runs no hook; collection (`ak run gc` and the
scheduled tick) asks the recorded pull request URL for its state and deletes the branch on origin
under `--force-with-lease` on the commit ak pushed, running the repository's own push hooks.
Black-box: runs `AK_BIN` from outside through tests/fixtures/akbin.py.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.fakegh import GitHub, OFFLINE
from fixtures.garbage import DAY, ROOM
from fixtures.gitrig import Rig

CONDITION = "if its pull request is closed unmerged and origin still holds it as pushed"


def plant_run(home, rig, gh, run_id, days, *, pr_state="CLOSED", push_rig=None, with_pr=True,
              review_pr=False, **fields):
    """Create a run checkout on `ak/<run_id>`, push its commit to `origin`, optionally open a PR
    in `pr_state`, and write its run record aged `days` back."""
    branch = f"ak/{run_id}"
    sha = rig.branch(branch, {f"{run_id}.txt": f"{run_id}\n"})
    wt = home.path / ".agentkit" / "wt" / run_id
    rig.git("worktree", "add", "-q", str(wt), branch)
    target = push_rig or rig
    url = gh.open_pr(target, branch, title=f"Change {run_id}") if with_pr else None
    if url and pr_state != "OPEN":
        gh.edit(int(url.rsplit("/", 1)[-1]), target.slug, state=pr_state)
    ended = time.time() - days * DAY
    record = {"run_id": run_id, "repo": str(rig.path), "worktree": str(wt), "branch": branch,
              "delivery_sha": sha, "pr": url, "review_pr": url if review_pr else None,
              "state": "fail", "merged": False, "started_at": ended - 600,
              "finished_at": ended, **fields}
    home.write(f".agentkit/runs/{run_id}/run.json",
               {key: value for key, value in record.items() if value is not None}, ago=days * DAY)
    return wt, branch, sha, url


def advance_origin_branch(rig, branch, sha):
    """Advance `origin`'s `branch` past `sha`, as a push after the run ended."""
    later = rig.origin("commit-tree", rig.origin("rev-parse", f"{sha}^{{tree}}"),
                       "-p", sha, "-m", "later push")
    rig.origin("update-ref", f"refs/heads/{branch}", later, sha)
    return later


def install_pre_push_hook(repo_path, script):
    hook = repo_path / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n" + script)
    hook.chmod(0o755)
    return hook


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class ClosedPullRequestBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.gh = gh = GitHub(home)
        cls.rig = rig = Rig(home, "widgets")

        # A second repository where `origin` fetches from `mirror` and pushes to `widgets-push`.
        cls.fetch_rig = fetch_rig = Rig(home, "widgets-mirror")
        cls.push_rig = push_rig = Rig(home, "widgets-push")
        fetch_rig.git("push", "-q", "--force", str(push_rig.bare), "main:main")
        fetch_rig.git("remote", "set-url", "--push", "origin", str(push_rig.bare))

        cls.closed_fail = plant_run(home, rig, gh, "closed-fail", 8)
        cls.closed_pass = plant_run(home, rig, gh, "closed-pass", 8, state="pass", no_merge=True)
        cls.old_closed = plant_run(home, rig, gh, "old-closed", 31)
        cls.old_gone_wt = plant_run(home, rig, gh, "old-tree-gone", 31)
        rig.git("worktree", "remove", "--force", str(cls.old_gone_wt[0]))
        cls.split_origin = plant_run(home, fetch_rig, gh, "split-origin", 8, push_rig=push_rig)
        cls.moved = plant_run(home, rig, gh, "moved-after", 8)
        cls.moved_tip = advance_origin_branch(rig, cls.moved[1], cls.moved[2])
        cls.open_pr = plant_run(home, rig, gh, "open-pr", 8, pr_state="OPEN")
        cls.merged_pr = plant_run(home, rig, gh, "merged-pr", 8, pr_state="MERGED")
        cls.no_pr = plant_run(home, rig, gh, "no-pr", 8, with_pr=False)
        cls.reviewed_pr = plant_run(home, rig, gh, "reviewed-pr", 8, review_pr=True)
        cls.kept = plant_run(home, rig, gh, "kept-young", 2)

        home.log("gh").unlink(missing_ok=True)
        dry_hook_mark = home.root / "dry-hook-ran"
        hook = install_pre_push_hook(rig.path, f'echo ran >>"{dry_hook_mark}"\nexit 1\n')
        cls.before_main = {b: rig.head(b) for b in rig.branches()}
        cls.before_push = {b: push_rig.head(b) for b in push_rig.branches()}

        cls.dry = home.ak("run", "gc", "--dry-run", boxed=True, env=ROOM)
        cls.dry_gh_calls = home.calls("gh")
        cls.dry_hook_touched = dry_hook_mark.exists()
        cls.after_dry_main = {b: rig.head(b) for b in rig.branches()}
        cls.after_dry_push = {b: push_rig.head(b) for b in push_rig.branches()}

        cls.push_hook_log = home.root / "pre-push.log"
        hook.unlink()
        install_pre_push_hook(rig.path, f'cat >>"{cls.push_hook_log}"\nexit 0\n')
        cls.collected = home.ak("run", "gc", boxed=True, env=ROOM)
        cls.gc_gh_calls = home.calls("gh")

    def test_dry_run_prints_conditional_line_calls_no_gh_or_hook_and_leaves_origin(self):
        self.assertEqual((self.dry.code, self.dry.err), (0, ""))
        self.assertEqual(self.dry_gh_calls, [])
        self.assertFalse(self.dry_hook_touched)
        self.assertEqual(self.after_dry_main, self.before_main)
        self.assertEqual(self.after_dry_push, self.before_push)

        lines = self.dry.out.splitlines()
        old_dir = self.home.path / ".agentkit" / "runs" / "old-closed"
        for target, branch in (*(row[:2] for row in (self.closed_fail, self.closed_pass,
                                                     self.split_origin, self.moved,
                                                     self.open_pr, self.merged_pr)),
                               (old_dir, self.old_closed[1])):
            matches = [i for i, line in enumerate(lines)
                       if line.startswith("gc: would remove ") and f" {target}" in line]
            self.assertEqual(len(matches), 1, lines)
            self.assertEqual(lines[matches[0] + 1],
                             f"gc: would remove remote-branch {branch}: {CONDITION}")
        self.assertEqual(len([line for line in lines if "remote-branch" in line]), 7)

    def test_closed_unmerged_pr_branch_goes_on_both_worktree_paths_and_split_origin(self):
        self.assertEqual((self.collected.code, self.collected.err), (0, ""))
        for wt, _, _, _ in (self.closed_fail, self.closed_pass, self.old_closed,
                            self.split_origin):
            self.assertFalse(wt.exists(), wt)
        for row in (self.closed_fail, self.closed_pass, self.old_closed):
            self.assertNotIn(row[1], self.rig.branches())
        self.assertEqual(self.fetch_rig.branches(), ["main"])
        self.assertEqual(self.push_rig.branches(), ["main"])
        hook_seen = self.push_hook_log.read_text()
        self.assertIn(f"refs/heads/{self.closed_fail[1]}", hook_seen)
        self.assertIn(f"refs/heads/{self.closed_pass[1]}", hook_seen)

    def test_moved_open_merged_and_prless_runs_keep_their_branches_while_worktrees_go(self):
        for wt, _, _, _ in (self.moved, self.open_pr, self.merged_pr, self.no_pr,
                            self.reviewed_pr):
            self.assertFalse(wt.exists(), wt)
        remaining = {b: self.rig.head(b) for b in self.rig.branches()}
        self.assertEqual(remaining.get(self.moved[1]), self.moved_tip)
        for _, branch, sha, _ in (self.open_pr, self.merged_pr, self.no_pr, self.reviewed_pr,
                                  self.old_gone_wt):
            self.assertEqual(remaining.get(branch), sha)
        self.assertIn(f"gc: kept remote-branch {self.moved[1]}:", self.collected.out)

    def test_a_kept_worktree_keeps_its_branch_and_asks_nothing_of_github(self):
        wt, branch, sha, url = self.kept
        self.assertTrue(wt.exists())
        self.assertEqual(self.rig.head(branch), sha)
        self.assertEqual(len(self.gc_gh_calls), 7)
        for call in self.gc_gh_calls:
            self.assertEqual((call[:2], call[3:]), (["pr", "view"], ["--json", "state"]))
            self.assertNotIn(call[2], (url, self.reviewed_pr[3], self.old_gone_wt[3]))

    def test_unanswered_pr_or_refusing_hook_is_reported_and_stops_nothing_else(self):
        with Home() as home:
            gh = GitHub(home)
            rig_a, rig_b, rig_c = Rig(home, "widgets-a"), Rig(home, "widgets-b"), Rig(home, "widgets-c")
            wt_a, branch_a, sha_a, url_a = plant_run(home, rig_a, gh, "offline-pr", 8)
            wt_b, branch_b, sha_b, _ = plant_run(home, rig_b, gh, "hook-no", 8)
            wt_gone, branch_gone, _, _ = plant_run(home, rig_c, gh, "already-gone", 8)
            wt_c, branch_c, _, _ = plant_run(home, rig_c, gh, "follows-through", 8)
            rig_c.origin("update-ref", "-d", f"refs/heads/{branch_gone}")
            gh.reply(f"pr view {url_a}", err=OFFLINE, code=1)
            install_pre_push_hook(rig_b.path, 'echo "policy refuses delete" >&2\nexit 1\n')

            done = home.ak("run", "gc", boxed=True, env=ROOM)
            self.assertEqual((done.code, done.err), (0, ""))
            for wt in (wt_a, wt_b, wt_gone, wt_c):
                self.assertFalse(wt.exists(), wt)
            self.assertEqual(rig_a.head(branch_a), sha_a)
            self.assertEqual(rig_b.head(branch_b), sha_b)
            self.assertEqual(rig_c.branches(), ["main"])
            for branch in (branch_a, branch_b, branch_gone):
                self.assertIn(f"gc: kept remote-branch {branch}:", done.out)
            self.assertIn(f"gc: remove remote-branch {branch_c}", done.out)

    def test_scheduled_collection_removes_closed_pr_branches_too(self):
        with Home() as home:
            config = home.path / ".agentkit" / "config.toml"
            config.write_text(config.read_text() + "\n[audit]\non = false\n")
            gh, rig = GitHub(home), Rig(home, "widgets")
            wt_fail, branch_fail, _, _ = plant_run(home, rig, gh, "tick-fail", 8)
            wt_pass, branch_pass, _, _ = plant_run(home, rig, gh, "tick-pass", 8, state="pass",
                                                   merge_note="checks failed")
            wt_open, branch_open, sha_open, _ = plant_run(home, rig, gh, "tick-open", 8,
                                                          pr_state="OPEN")

            done = home.tick(env=ROOM)
            self.assertEqual(done.code, 0, done.err)
            for wt in (wt_fail, wt_pass, wt_open):
                self.assertFalse(wt.exists(), wt)
            self.assertEqual(rig.branches(), [branch_open, "main"])
            self.assertEqual(rig.head(branch_open), sha_open)
            log = (home.path / ".agentkit" / "state" / "gc.log").read_text()
            self.assertIn(f"gc: remove remote-branch {branch_fail}", log)
            self.assertIn(f"gc: remove remote-branch {branch_pass}", log)


if __name__ == "__main__":
    unittest.main()
