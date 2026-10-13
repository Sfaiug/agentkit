"""The scoreboard counts the merged changes a later change rewrote within a week of their merge.

A change answers for its lines for `scoreboard.ANSWERS_FOR` after it merges: a later change on
the default branch that deletes a line it added inside that window is a defect its review let
through, a revert among them.  The board counts those per week and per reviewer, followed
from each merged run's merge commit, which its history row keeps.  Offline: a git repository
the test writes, with commit dates it sets, and no network.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, record, scoreboard, watch

NOW = 1_800_000_000
DAY = 86400


class EscapedDefects(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-escaped-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.root))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        for name in ("RUNS", "REPO"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.object(config, "CODE", self.root))     # holds `widget`
        stack.enter_context(patch.object(scoreboard.time, "time", return_value=NOW))
        stack.enter_context(patch.object(config, "session_records", return_value={}))
        history._OPEN.clear()
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.commit(NOW - 20 * DAY, {"file.py": "a\nb\nc\n", "other.py": "x = 1\n"})

    def git(self, *args, when=None):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        if when is not None:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = str(when)
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True, env=env).stdout.strip()

    def commit(self, when, files):
        """One commit on main at `when`, writing `files`; its sha."""
        for name, text in files.items():
            (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change", when=when)
        return self.git("rev-parse", "HEAD")

    def merged(self, run_id, sha, when, reviewer="opus"):
        """A run's row, merged as `sha` at `when`; `reviewer` None is a review ak skipped."""
        history.start_run(run_id, repo=str(self.repo), started_at=when - 3600, change=run_id)
        history.finish_run(run_id, final_state="pass", finished_at=when, changed_lines=0,
                           reviewer=reviewer)
        history.update_run(run_id, merge_sha=sha)

    def test_a_line_deleted_within_a_week_of_its_merge_is_a_defect_that_escaped(self):
        # merged 12 days ago, its line rewritten 2 days later: escaped, window closed
        old = self.commit(NOW - 12 * DAY, {"file.py": "a\nb\nc\ndef parse():\n    return 1\n"})
        self.commit(NOW - 10 * DAY, {"file.py": "a\nb\nc\ndef parse():\n    return 2\n"})
        # merged 9 days ago, reverted the next day: escaped
        revert = self.commit(NOW - 9 * DAY, {"other.py": "x = 1\ny = 3\n"})
        self.commit(NOW - 8 * DAY, {"other.py": "x = 1\n"})
        # merged 11 days ago, its line rewritten only 8 days later: not within the week
        late = self.commit(NOW - 11 * DAY, {"late.py": "z = 4\n"})
        self.commit(NOW - 3 * DAY, {"late.py": "z = 5\n"})
        # merged 6 days ago, nothing rewrote it yet: still inside its week
        fresh = self.commit(NOW - 6 * DAY, {"fresh.py": "w = 6\n"})
        # merged 5 days ago, only a line without a letter or digit deleted since: not a defect
        bare = self.commit(NOW - 5 * DAY, {"bare.py": "# ---\nv = 7\n"})
        self.commit(NOW - 4 * DAY, {"bare.py": "v = 7\n"})
        # merged 13 days ago, its line moved to another file the next day: a move, not a rewrite
        mover = self.commit(NOW - 13 * DAY, {"m.py": "q = 9\n"})
        self.commit(NOW - 12 * DAY, {"m.py": "", "n.py": "q = 9\n"})
        for run_id, sha, days, reviewer in (("old", old, 12, "gpt-sol"), ("revert", revert, 9, "opus"),
                                             ("late", late, 11, "gpt-sol"), ("fresh", fresh, 6, None),
                                             ("bare", bare, 5, "opus"), ("mover", mover, 13, "opus")):
            self.merged(run_id, sha, NOW - days * DAY, reviewer)
        self.merged("lost", None, NOW - 2 * DAY)        # merged with no merge commit recorded
        log = scoreboard.branch_log(self.repo, NOW - 21 * DAY)
        self.assertEqual((len(log), log[1]["sha"]), (12, old))     # the base commit, then oldest first
        self.assertEqual(scoreboard.escaped(log, old, NOW), (1, False))
        self.assertEqual(scoreboard.escaped(log, revert, NOW), (1, False))
        self.assertEqual(scoreboard.escaped(log, late, NOW), (0, False))
        self.assertEqual(scoreboard.escaped(log, fresh, NOW), (0, True))
        self.assertEqual(scoreboard.escaped(log, bare, NOW), (0, True))
        self.assertEqual(scoreboard.escaped(log, mover, NOW), (0, False))
        self.assertIsNone(scoreboard.escaped(log, "0" * 40, NOW))
        [this_week, before] = scoreboard.compute(NOW)["escaped"]
        self.assertEqual(this_week, {"merged": 2, "escaped": 0, "open": 2, "unknown": 1,
                                     "reviewers": {"no reviewer": [0, 1], "opus": [0, 1]}})
        self.assertEqual(before, {"merged": 4, "escaped": 2, "open": 0, "unknown": 0,
                                  "reviewers": {"gpt-sol": [1, 2], "opus": [1, 2]}})
        with patch.object(scoreboard.terminal, "content_width", return_value=400):
            board = "\n".join(scoreboard.render())
        self.assertIn("escaped   0 of 2 merged changes had a line rewritten within 7 days (no reviewer 0 of 1, "
                      "opus 0 of 1); 2 merged under 7 days ago may still be; 1 with no merge commit to follow",
                      board)
        self.assertIn("2 of 4 merged changes had a line rewritten within 7 days (gpt-sol 1 of 2, opus 1 of 2)",
                      board)

    def test_a_week_with_no_merged_change_follows_nothing(self):
        history.start_run("open", repo=str(self.repo), started_at=NOW - 3600, change="open")
        history.finish_run("open", final_state="fail", finished_at=NOW - 1800)
        self.assertEqual(scoreboard.compute(NOW)["escaped"], [None, None])
        with patch.object(scoreboard.terminal, "content_width", return_value=400):
            self.assertIn("escaped   no merged change", "\n".join(scoreboard.render()))

    def test_every_line_of_the_patch_is_read_whatever_its_text_its_name_or_git_config(self):
        # a deleted `-- ` line reads `--- ` in the patch and an added `++ ` line `+++ `, as a
        # file's header does; a name Git quotes; prefixes the user turned off
        self.git("config", "core.quotePath", "true")
        cases = (("schema.sql", "-- original comment\nSELECT 1;\n", "-- revised comment\nSELECT 2;\n"),
                 ("counter.cc", "int counter = 0;\n++ counter;\nint answer = 1;\n",
                  "int counter = 0;\n++ counter;\nint answer = 2;\n"),
                 ("r\u00e9sum\u00e9.py", "answer = 1\n", "answer = 2\n"))
        merges = [self.commit(NOW - 6 * DAY, {name: before}) for name, before, _ in cases]
        for name, _, after in cases:
            self.commit(NOW - 4 * DAY, {name: after})
        log = scoreboard.branch_log(self.repo, NOW - 21 * DAY)
        self.assertEqual([scoreboard.escaped(log, sha, NOW) for sha in merges], [(1, True)] * 3)
        self.git("config", "diff.noprefix", "true")
        self.assertEqual(scoreboard.branch_log(self.repo, NOW - 21 * DAY), log)

    def test_the_tick_keeps_the_merge_commit_it_learns_with_no_health_to_follow(self):
        sha = self.commit(NOW - 3600, {"file.py": "a\nb\nc\nd = 1\n"})
        directory = config.RUNS / "kept"
        directory.mkdir(parents=True)
        record.save_state(directory, {"run_id": "kept", "state": "pass", "merged": True,
                                      "finished_at": NOW - 1800, "repo": str(self.repo),
                                      "pr": "https://github.com/acme/widget/pull/7"})
        history.start_run("kept", repo=str(self.repo), started_at=NOW - 7200, change="kept")
        with patch.object(watch, "gh_json", return_value=({"mergeCommit": {"oid": sha}}, "")) as api, \
                patch.object(watch, "after_merge_status", return_value=("passed", None, None)), \
                patch.object(watch, "save_state"):
            for _ in range(2):
                watch.after_merge_checks({}, False, lambda _: None, now=NOW)
        self.assertEqual(api.call_count, 1)        # asked once, then read from the record
        self.assertEqual(record.read_state(directory)["merge_sha"], sha)
        self.assertEqual(history.get("kept")["merge_sha"], sha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
