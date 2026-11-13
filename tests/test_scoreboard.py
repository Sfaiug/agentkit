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


# these numbers never pick a model. [2 Oct, 14 Oct, 27 Oct]
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
        # Old databases kept the suites' rows, under the one checkout name every suite gave its
        # clone, and suite repos identifiable only by their record.
        self.ended("old-name", tokens=(10000, 10000))
        self.ended("old-tmp", tokens=(10000, 10000))
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("UPDATE runs SET repo='agentkit-smoke' WHERE run_id='old-name'")
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

    def test_size_counts_only_tracked_code_readme_and_agents_words_at_both_commits(self):
        files = {"agentkit/core.py": "one\ntwo\n", "bin/ak": "one\ntwo\n",
                 "hooks/on.sh": "one\n", "adapters/echo.sh": "one\n",
                 "tools/tool.py": "one\n", "install.sh": "one\n",
                 "README.md": "two words\n", "AGENTS.md": "one\n", "docs/notes.md": "ignored\n" * 100,
                 "tests/test_fixture.py": "ignored\n" * 100}
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(content)
        self.commit(9 * 86400)
        (self.repo / "agentkit/core.py").write_text("one\ntwo\nthree\nfour\n")
        (self.repo / "install.sh").write_text("one\ntwo\n")
        (self.repo / "README.md").write_text("one two three four five\n")
        (self.repo / "AGENTS.md").write_text("one two three\n")
        (self.repo / "tools/binary").write_bytes(b"\0binary\n" * 100)
        self.commit(3 * 86400)
        (self.repo / "agentkit/untracked.py").write_text("ignored\n" * 100)
        (self.repo / "agentkit/core.py").write_text("uncommitted\n" * 100)
        self.assertEqual(scoreboard.compute(NOW)["size"], [
            {"code_lines": 11, "readme_words": 5, "agents_words": 3},
            {"code_lines": 8, "readme_words": 2, "agents_words": 1}])

    def test_new_install_and_missing_git_or_database_use_words_for_missing_data(self):
        (self.repo / "README.md").write_text("new install\n")
        self.commit(1)
        board = scoreboard.compute(NOW)
        self.assertEqual(board["size"], [{"code_lines": 0, "readme_words": 2, "agents_words": None}, None])
        self.assertFalse(history.path().exists())
        with patch.object(scoreboard.subprocess, "run", side_effect=OSError("git unavailable")):
            board = scoreboard.compute(NOW)
        self.assertEqual(board, {"products": [None, None], "ak": [None, None], "tokens": [None, None],
                                 "intent": [None, None],
                                 "owner": [None, None],
                                 "built": [None, None], "waits": [None, None], "merged": [None, None],
                                 "checks": [None, None],
                                 "parks": [None, None], "conflicts": [None, None],
                                 "sunk": [None, None], "broke": [None, None], "rewritten": [None, None],
                                 "pairs": [None, None], "findings": [None, None], "size": [None, None]})
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
        self.assertEqual(scoreboard.compute(NOW)["checks"], [None, None])
        self.assertEqual(scoreboard.compute(NOW)["rewritten"], [None, None])
        self.assertEqual(history.path().read_bytes(), before)

    def test_review_pairs_count_merged_changes_with_known_pairs_and_landing_results(self):
        cases = (("self-red", "self", 2), ("self-green", "self", 0),
                 ("same", "same provider", 0), ("other", "other provider", 1),
                 ("unknown", None, 1), ("unmerged", "self", 1),
                 ("previous", "same provider", None), ("earlier", "other provider", 1))
        for name, pair, red in cases:
            self.ended(name, ago=WEEK + 1 if name == "previous" else 2 if name == "earlier" else 1,
                       merged=name != "unmerged")
            with sqlite3.connect(history.path()) as db:
                db.execute("UPDATE runs SET review_pair=?, landing_breaks=?, change=? WHERE run_id=?",
                           (pair, red, "acme/widgets#1" if name in ("earlier", "same") else name, name))
        self.assertEqual(scoreboard.compute(NOW)["pairs"], [
            {"self": .5, "self_landing": .5, "same_provider": .25,
             "same_provider_landing": 0, "other_landing": 1},
            {"self": 0, "self_landing": None, "same_provider": 1,
             "same_provider_landing": None, "other_landing": None}])

    def test_findings_match_earlier_blocking_rounds_and_count_each_date_boundary_once(self):
        history.start_run("fix-api", repo="acme", started_at=NOW - 3 * WEEK)
        rows = [(1, "api.py", "finding", "first", NOW - 2 * WEEK - 1),
                (2, "api.py", "finding", "first", NOW),
                (2, "api.py", "finding", "first", NOW - WEEK),
                (2, "api.py", "finding", "second", NOW - 1),
                (2, "api.py", "finding", "second", NOW - 2),
                (3, "other.py", "finding", "first", NOW - 3),
                (1, "api.py", "note", "note proof", NOW - 10),
                (2, "api.py", "finding", "note proof", NOW - 4),
                (1, "before.py", "finding", "old", NOW - 2 * WEEK),
                (3, "api.py", "finding", "first", NOW + 1)]
        with closing(sqlite3.connect(history.path())) as db, db:
            db.executemany("INSERT INTO findings (run_id, round, path, kind, proof, at) "
                           "VALUES ('fix-api', ?, ?, ?, ?, ?)", rows)
        self.assertEqual(scoreboard.compute(NOW)["findings"], [
            {"blocking": 6, "disputed": 0, "conceded": 0, "raised_again": 2, "let_go": 0, "let_go_broke": 0,
             "later": 0, "inside_fix": 0},
            {"blocking": 1, "disputed": 0, "conceded": 0, "raised_again": 0, "let_go": 0, "let_go_broke": 0,
             "later": 0, "inside_fix": 0}])

    def test_render_keeps_the_existing_text(self):
        board = {
            "products": [{"runs": 3, "merged": 2, "first_round": 1 / 3, "unmerged": 1 / 3,
                          "hours": 1.5, "tokens": 1500}, None],
            "ak": [{"runs": 1, "merged": 0, "first_round": 0, "unmerged": 1,
                    "hours": None, "tokens": None, "token_share": .6},
                   {"runs": 1, "merged": 1, "first_round": 1, "unmerged": 0,
                    "hours": None, "tokens": None, "token_share": None}],
            "size": [{"code_lines": 17, "readme_words": 5, "agents_words": 9}, None],
            "tokens": [None, None],
            "intent": [None, {"measured": 0, "hours": None, "live": 0, "live_hours": None, "answer_share": None}],
            "owner": [{"asked": 2, "paged": 3, "hours": 1.25}, {"asked": 0, "paged": 0, "hours": None}],
            "built": [None, None],
            "waits": [{"compute": .25, "merge_hours": 1.5, "lander_hours": .5}, None],
            "merged": [{"model": 1.375, "ak": 1.875, "waiting": 0.75, "seat": 1.0}, None],
            "checks": [{"suites": 1.32, "hours": 1.45}, None],
            "parks": [None, None],
            "conflicts": [None, None],
            "sunk": [{"share": .4, "tokens": 1200}, None],
            "broke": [{"merged": 2, "after_merge": 1, "landing": 1, "flakes": 2, "unknown": 1}, None],
            "rewritten": [{"live": 3, "rewritten": 1}, {"live": 0, "rewritten": 0}],
            "pairs": [{"self": .5, "self_landing": .25, "same_provider": .3,
                       "same_provider_landing": .4, "other_landing": .1}, None],
            "findings": [{"blocking": 4, "disputed": 3, "conceded": 2, "raised_again": 1,
                          "let_go": 3, "let_go_broke": 2, "later": 2, "inside_fix": 1}, None],
        }
        expected = [
            "Scoreboard (reported tokens; size now and 7 days ago)",
            "              last 7 days                                 7 days before",
            "products      3 runs ended; 33% merged in round 1; 33%    no runs ended",
            "              ended without merging; median 1.5 hours to",
            "              merge; median 1,500 tokens per merged run",
            "ak            1 runs ended; 0% merged in round 1; 100%    1 runs ended; 100% merged in round 1; 0%",
            "              ended without merging; no merged runs; 60%  ended without merging; merge hours",
            "              of all recorded tokens                      unknown; median tokens per merged run",
            "                                                          unknown; no tokens recorded",
            "tokens        no tokens recorded                          no tokens recorded",
            "intent        not recorded                                no intent measured",
            "owner         2 questions asked, 3 cards sent, median     0 questions asked, 0 cards sent",
            "              1.2 hours waiting for an answer",
            "built         no runs ended                               no runs ended",
            "waits         25% of run time waiting for a slot or its   not recorded",
            "              own suite turn; 1.5 hours in a landing",
            "              line, where checks waited 0.5 hours for a",
            "              suite turn",
            "merged        median hours per merged change: 1.4 in      no merged change",
            "              model turns, 1.9 ak's own work, 0.8",
            "              waiting, 1.0 with its seat between runs",
            "checks        1.32 suite runs and 1.45 check hours per    not recorded",
            "              merged change",
            "parks         not recorded                                not recorded",
            "conflicts     no merged change                            no merged change",
            "sunk          40% of the week's tokens, 1,200, went to    no tokens recorded",
            "              runs that never merged",
            "broke         1 of 2 merged changes broke main or live    no merged change",
            "              after merge; 1 went red at landing; 2 more",
            "              were flakes; 1 merged before breaks were",
            "              recorded",
            "rewritten     1 of 3 live plan lines rewritten within 14  no plan line went live",
            "              days",
            "review pairs  50% self-reviewed (25% went red at          not recorded",
            "              landing); 30% reviewed by another model of",
            "              the same provider (40% went red at",
            "              landing); another provider: 10% went red",
            "              at landing",
            "findings      4 blocking; 3 disputed; 2 of 3 conceded; 1  not recorded",
            "              of 4 raised again; 3 let go; 2 of 3 on a",
            "              change that broke main or live after",
            "              merge; 1 of 2 handed in after round 1",
            "              inside the fix",
            "ak size       17 code lines, 5 README words, 9 AGENTS.md  size unavailable",
            "              words",
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
