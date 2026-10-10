"""The history scoreboard measures delivered work and ak's cost, never its models.

Offline: a local git history, a sandbox HOME and recorded run rows.
"""

from contextlib import ExitStack, closing, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gate, config, history, run, status, scoreboard, terminal

NOW = 1_800_000_000
WEEK = 7 * 86400


class Scoreboard(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-scoreboard-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "toolkit"
        self.repo.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "NO_COLOR": "1"}))
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        self.stack.enter_context(patch.object(config, "RUNS", config.HOME / "runs"))
        self.stack.enter_context(patch.object(config, "REPO", self.repo))
        self.stack.enter_context(patch.object(gate, "host_status_line", return_value="host fixture"))
        self.stack.enter_context(patch.object(config, "load", return_value={"models": {}, "providers": {}}))
        self.stack.enter_context(patch.object(scoreboard.time, "time", return_value=NOW))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")

    def git(self, *args, env=None):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True,
                              env={**os.environ, **(env or {})}).stdout.strip()

    def commit(self, ago):
        self.git("add", "-A")
        date = f"@{NOW - ago} +0000"
        self.git("commit", "-qm", "fixture",
                 env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})

    def ended(self, name, repo="acme", *, ago=1, state="pass", rounds=1,
              hours=1, tokens=(80, 20), merged=True):
        finish = NOW - ago
        history.start_run(name, repo=repo, started_at=finish - hours * 3600)
        history.finish_run(name, final_state=state, verdict=state.upper(),
                           finished_at=finish, rounds_used=rounds,
                           changed_lines=0 if merged else None)
        history.update_run(name, executor_tokens=tokens[0], reviewer_tokens=tokens[1])

    def saved(self, name, **state):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(json.dumps(state))

    def status(self, *args):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(status.cmd_status(list(args)), 0)
        return out.getvalue()

    def test_two_weeks_measure_endings_merges_wall_time_and_all_role_tokens(self):
        self.ended("first", hours=1)
        self.ended("later", rounds=3, hours=3, tokens=(180, 20))
        for state in ("fail", "error", "blocked", "exhausted"):
            self.ended(state, state=state, tokens=(40, 10), merged=False)
        # A passed scratch run is an ending, but it delivered no merge.
        self.ended("scratch", merged=False)
        self.ended("own", repo="toolkit", rounds=2, hours=5, tokens=(300, 100))
        self.ended("own-fail", repo="toolkit", state="fail", tokens=(400, 100), merged=False)
        self.ended("before", ago=WEEK + 1, hours=8, tokens=(300, 100))
        self.ended("before-blocked", ago=WEEK + 2, state="blocked", merged=False)
        self.ended("own-before", repo="toolkit", ago=WEEK + 1, tokens=(800, 200))
        board = scoreboard.compute(NOW)
        self.assertEqual(board["products"][0], {
            "runs": 7, "merged": 2, "first_round": 1 / 7, "unmerged": 4 / 7,
            "hours": 2, "tokens": 150})
        self.assertEqual(board["products"][1], {
            "runs": 2, "merged": 1, "first_round": .5, "unmerged": .5,
            "hours": 8, "tokens": 400})
        current, previous = board["ak"]
        self.assertEqual((current["runs"], current["first_round"], current["unmerged"]), (2, 0, .5))
        self.assertEqual((current["hours"], current["tokens"], current["token_share"]), (5, 400, .6))
        self.assertEqual((previous["runs"], previous["tokens"], previous["token_share"]), (1, 1000, 2 / 3))

    def test_finish_date_defines_the_week_and_each_boundary_counts_once(self):
        self.ended("now", ago=0, hours=24 * 20)
        self.ended("seven", ago=WEEK)
        self.ended("fourteen", ago=2 * WEEK)
        self.ended("old", ago=2 * WEEK + 1)
        self.ended("future", ago=-1)
        self.ended("still-running", state="running")
        self.ended("waiting-login", state="waiting_login")
        board = scoreboard.compute(NOW)
        self.assertEqual([stats["runs"] for stats in board["products"]], [2, 1])
        self.assertEqual(board["ak"], [None, None])

    def test_stopped_and_old_suite_rows_are_excluded_from_every_number(self):
        self.ended("real")
        self.ended("stopped", state="stopped", tokens=(10000, 10000))
        self.ended("old-smoke", repo="agentkit-smoke", tokens=(10000, 10000))
        # Old databases kept both suite names and suite repos identifiable only by their record.
        self.ended("old-e2e", tokens=(10000, 10000))
        self.ended("old-tmp", tokens=(10000, 10000))
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("UPDATE runs SET repo='agentkit-e2e' WHERE run_id='old-e2e'")
        self.saved("old-tmp", repo="/home/acme/.agentkit/tmp/suite/repo-retry")
        board = scoreboard.compute(NOW)
        self.assertEqual(board["products"][0]["runs"], 1)
        self.assertEqual(board["products"][0]["tokens"], 100)
        self.assertEqual(board["ak"], [None, None])
        self.ended("own", repo="toolkit")
        self.assertEqual(scoreboard.compute(NOW)["ak"][0]["token_share"], .5)

    def test_merge_evidence_survives_cleanup_and_pass_alone_is_not_a_merge(self):
        self.ended("durable", rounds=2)
        self.ended("legacy", merged=False)
        self.saved("legacy", merged=True)
        self.ended("pass-only", merged=False)
        stats = scoreboard.compute(NOW)["products"][0]
        self.assertEqual((stats["runs"], stats["merged"], stats["first_round"]), (3, 2, 1 / 3))

    def test_missing_token_measurements_stay_unknown_and_medians_ignore_outliers(self):
        self.ended("unknown", tokens=(100, None))
        self.assertIsNone(scoreboard.compute(NOW)["products"][0]["tokens"])
        text = " ".join(self.status("--history").split())
        self.assertIn("median tokens per merged run unknown", text)
        for name, hours, tokens in (("one", 1, (0, 0)), ("two", 2, (120, 80)),
                                    ("outlier", 1000, (80000, 20000))):
            self.ended(name, hours=hours, tokens=tokens)
        stats = scoreboard.compute(NOW)["products"][0]
        self.assertEqual((stats["hours"], stats["tokens"]), (1.5, 200))
        self.ended("large-cost", repo="toolkit", tokens=(1200000, 300001))
        self.assertIn("1,500,001 tokens", " ".join(self.status("--history").split()))

    def test_install_root_identifies_ak_under_any_name_even_in_a_worktree(self):
        (self.repo / "README.md").write_text("fixture\n")
        self.commit(1)
        installed = self.root / "installed"
        self.git("worktree", "add", "-q", "-b", "installed", str(installed))
        self.ended("own", repo="toolkit")
        self.ended("product-named-agentkit", repo="agentkit", tokens=(180, 20))
        with patch.object(config, "REPO", installed):
            board = scoreboard.compute(NOW)
        self.assertEqual(board["ak"][0]["runs"], 1)
        self.assertEqual(board["products"][0]["runs"], 1)
        self.assertEqual(board["ak"][0]["token_share"], 1 / 3)

    def test_size_counts_only_tracked_code_and_readme_words_at_both_commits(self):
        files = {"agentkit/core.py": "one\ntwo\n", "bin/ak": "one\ntwo\n",
                 "hooks/on.sh": "one\n", "adapters/echo.sh": "one\n",
                 "tools/tool.py": "one\n", "install.sh": "one\n",
                 "README.md": "two words\n", "docs/notes.md": "ignored\n" * 100,
                 "tests/test_fixture.py": "ignored\n" * 100}
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(content)
        self.commit(9 * 86400)
        (self.repo / "agentkit/core.py").write_text("one\ntwo\nthree\nfour\n")
        (self.repo / "install.sh").write_text("one\ntwo\n")
        (self.repo / "README.md").write_text("one two three four five\n")
        (self.repo / "tools/binary").write_bytes(b"\0binary\n" * 100)
        self.commit(3 * 86400)
        (self.repo / "agentkit/untracked.py").write_text("ignored\n" * 100)
        (self.repo / "agentkit/core.py").write_text("uncommitted\n" * 100)
        self.assertEqual(scoreboard.compute(NOW)["size"], [
            {"code_lines": 11, "readme_words": 5}, {"code_lines": 8, "readme_words": 2}])

    def test_new_install_and_missing_git_or_database_use_words_for_missing_data(self):
        (self.repo / "README.md").write_text("new install\n")
        self.commit(1)
        board = scoreboard.compute(NOW)
        self.assertEqual(board["size"], [{"code_lines": 0, "readme_words": 2}, None])
        self.assertFalse(history.path().exists())
        with patch.object(scoreboard.subprocess, "run", side_effect=OSError("git unavailable")):
            board = scoreboard.compute(NOW)
        self.assertEqual(board, {"products": [None, None], "ak": [None, None], "waits": [None, None],
                                 "merged": [None, None], "size": [None, None]})
        text = self.status("--history")
        self.assertIn("no runs ended", text)
        self.assertIn("size unavailable", text)
        self.assertNotIn("0 runs ended", text)

    def test_old_schema_can_supply_a_merge_without_being_migrated_or_rewritten(self):
        config.HOME.mkdir(parents=True)
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("CREATE TABLE runs (run_id TEXT, repo TEXT, final_state TEXT, "
                       "rounds_used INTEGER, started_at REAL, finished_at REAL, "
                       "executor_tokens INTEGER, reviewer_tokens INTEGER)")
            db.execute("INSERT INTO runs VALUES ('old', 'acme', 'pass', 1, ?, ?, 80, 20)",
                       (NOW - 3601, NOW - 1))
        self.saved("old", merged=True)
        before = history.path().read_bytes()
        stats = scoreboard.compute(NOW)["products"][0]
        self.assertEqual((stats["runs"], stats["hours"], stats["tokens"]), (1, 1, 100))
        self.assertEqual(history.path().read_bytes(), before)

    def test_render_keeps_the_existing_text(self):
        board = {
            "products": [{"runs": 3, "merged": 2, "first_round": 1 / 3, "unmerged": 1 / 3,
                          "hours": 1.5, "tokens": 1500}, None],
            "ak": [{"runs": 1, "merged": 0, "first_round": 0, "unmerged": 1,
                    "hours": None, "tokens": None, "token_share": .6},
                   {"runs": 1, "merged": 1, "first_round": 1, "unmerged": 0,
                    "hours": None, "tokens": None, "token_share": None}],
            "size": [{"code_lines": 17, "readme_words": 5}, None],
            "waits": [None, None],
            "merged": [{"model": 1.375, "ak": 1.875, "waiting": 0.75, "seat": 1.0}, None],
        }
        expected = [
            "Scoreboard (reported tokens; size now and 7 days ago)",
            "          last 7 days                                   7 days before",
            "products  3 runs ended; 33% merged in round 1; 33%      no runs ended",
            "          ended without merging; median 1.5 hours to",
            "          merge; median 1,500 tokens per merged run",
            "ak        1 runs ended; 0% merged in round 1; 100%      1 runs ended; 100% merged in round 1; 0%",
            "          ended without merging; no merged runs; 60%    ended without merging; merge hours unknown;",
            "          of all recorded tokens                        median tokens per merged run unknown; no",
            "                                                        tokens recorded",
            "waits     not recorded                                  not recorded",
            "merged    median hours per merged change: 1.4 in model  no merged change",
            "          turns, 1.9 ak's own work, 0.8 waiting, 1.0",
            "          with its seat between runs",
            "ak size   17 code lines, 5 README words                 size unavailable",
        ]
        with patch.object(scoreboard, "compute", return_value=board), \
                patch.object(terminal, "content_width", return_value=100):
            self.assertEqual(scoreboard.render(), expected)
            self.assertIn("\n".join(expected) + "\n", self.status("--history"))

    def test_status_prints_the_board_only_for_human_history_and_wraps_both_weeks(self):
        self.ended("product")
        self.ended("own", repo="toolkit", state="fail", merged=False)
        for width in (100, 40):
            with patch.object(terminal, "content_width", return_value=width):
                lines = scoreboard.render()
            self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
            self.assertTrue(all(line == line.rstrip() for line in lines))
            self.assertNotIn("…", "\n".join(lines))
            for word in ("products", "ak", "no merged runs", "no runs ended"):
                self.assertIn(word, " ".join(" ".join(lines).split()))
        with patch.object(scoreboard, "compute", wraps=scoreboard.compute) as board:
            self.assertNotIn("Scoreboard", self.status())
            self.assertEqual(json.loads(self.status("--history", "--json")), [])
            board.assert_not_called()
            for args in (("--history",), ("--history", "--plain")):
                text = self.status(*args)
                self.assertIn("Scoreboard", text)
                self.assertIn("last 7 days", text)
                self.assertIn("7 days before", text)
                self.assertNotIn("ceiling", text)
        self.assertEqual(board.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
