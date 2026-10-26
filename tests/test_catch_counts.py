"""Finished, weighed reviews reach history under a test HOME."""

from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, hand_in, history, run, staffing, transitions, turns, worker


class CatchCounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-catches-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(history._OPEN.clear)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "AGENTKIT_RUN": "", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, key, config.HOME / key.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        for module, name in ((worker, "kill_marked"), (turns, "memory_cap_note"),
                             (transitions, "history_role_tokens")):
            self.stack.enter_context(patch.object(module, name, return_value=None))
        self.cfg = {"models": {}, "providers": {"acme": {}, "beta": {}},
                    "defaults": {"orchestrator": "builder", "workers": ["builder"],
                                 "reviewers": ["reviewer", "spare"]}}
        for name, harness, model, provider in (
                ("builder", "test", "build-1", "acme"),
                ("reviewer", "test", "judge-1", "beta"),
                ("spare", "test", "judge-2", "beta")):
            self.cfg["models"][name] = {"harness": harness, "model": model,
                                        "effort": "high", "provider": provider}
        config.ensure_dirs()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        run.git(self.repo, "init", "-qb", "main")
        run.git(self.repo, "config", "user.name", "Fixture")
        run.git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "api.txt").write_text("good\nold defect\n")
        self.commit("Existing behaviour")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        run.git(self.repo, "checkout", "-qb", "ak/fix-api")
        (self.repo / "api.txt").write_text("bad\nold defect\n")
        self.commit("Introduce a regression")

    def commit(self, message):
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-qm", message)

    def loop(self, name="fix-api", **fields):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": "Fix the API", "state": "running", "started_at": 1,
                 "repo": str(self.repo), "worktree": str(self.repo), "base": "main",
                 "base_sha": self.base, "branch": "ak/fix-api", "executor": "builder",
                 "reviewer": "reviewer", "rounds": 3, "round_summaries": [], **fields}
        run.history_start(state)
        lp = run.Loop(self.cfg, directory, state, {}, lambda _: None, self.repo,
                      "Review the API.", ["true"], "")
        lp.rnd = 1
        lp.validation = run.commit_identity(self.repo)
        return lp

    def records(self):
        rows = []
        for line, what, command in (
                (1, "regression", 'python3 -c \'from pathlib import Path; '
                 'assert Path("api.txt").read_text().startswith("good")\''),
                (2, "existing defect", 'python3 -c \'from pathlib import Path; '
                 'assert "old defect" not in Path("api.txt").read_text()\''),
                (1, "unproven defect", "true")):
            rows.append({"kind": "finding", "path": "api.txt", "line": line,
                         "what": what, "why": "breaks callers",
                         "evidence": {"run": command, "returncode": 1, "output": "fixture"}})
        return rows

    def turn(self, rows, *, done=True):
        def call(_cfg, _model, _body, cwd, out, role, *_args, **_kw):
            out.mkdir(parents=True, exist_ok=True)
            file = hand_in.start(out, cwd, role=role)
            with Path(file).open("a") as output:
                for row in rows + ([{"kind": "done"}] if done else []):
                    output.write(json.dumps(row) + "\n")
            (out / "final.md").write_text("Handed in.")
            return 0, "Handed in.", "fixture-session", False
        return call

    def review(self, lp, rows=(), *, record=True):
        with patch.object(turns, "call_retrying", side_effect=self.turn(list(rows))):
            return run.review(lp, "API fixed.", True, "$ true\n[exit 0]\n", record=record)

    def reviews(self):
        """Each review recorded: the model that ran it, its blocking findings, follow-ups, notes."""
        with closing(sqlite3.connect(history.path())) as db:
            return db.execute("SELECT model, blocking, followup, note FROM reviews "
                              "ORDER BY rowid").fetchall()

    def test_weighed_counts_reach_the_database(self):
        lp = self.loop()
        self.assertEqual(self.review(lp, self.records()), "FAIL")
        with closing(sqlite3.connect(history.path())) as db:
            rows = db.execute("SELECT run_id, harness, model, blocking, followup, note, round, "
                              "verdict, effort FROM reviews").fetchall()
        self.assertEqual(rows, [("fix-api", "test", "judge-1", 1, 1, 1, 1, "FAIL", "high")])
        self.assertEqual(history.path(), self.root / ".agentkit/history.db")
        # The run row changes reviewer; its earlier review still belongs to judge-1.
        lp.rnd = 2
        lp.reviewer = "spare"
        self.assertEqual(self.review(lp), "FAIL")      # ak's own replay blocks: no catch of the spare's
        run.history_finish({**lp.state, "state": "pass"})
        self.assertEqual(self.reviews(), [("judge-1", 1, 1, 1), ("judge-2", 0, 0, 0)])

    def test_a_clean_landing_review_counts_without_spending_a_round(self):
        lp = self.loop()
        self.assertEqual(self.review(lp, self.records()), "FAIL")
        self.assertEqual(self.review(lp, record=False), "PASS")
        self.assertEqual(len(lp.state["round_summaries"]), 1)
        for _ in range(2):
            run.history_finish({**lp.state, "state": "pass"})
        self.assertEqual(self.reviews(), [("judge-1", 1, 1, 1), ("judge-1", 0, 0, 0)])

    def test_an_unfinished_reviewer_contributes_nothing(self):
        lp = self.loop()
        call = self.turn(self.records(), done=False)

        def extra(*args, **kwargs):
            return (*call(*args, **kwargs), False)

        with patch.object(turns, "call_retrying", side_effect=call), \
                patch.object(worker, "turn", side_effect=extra), \
                patch.object(staffing, "collect_usage", return_value={}), \
                patch.object(staffing, "ready_order", return_value=[]):
            with self.assertRaises(run.Exhausted):
                run.review(lp, "API fixed.", True, "$ true\n[exit 0]\n")
        self.assertEqual(self.reviews(), [])

    def test_an_old_database_takes_a_review_and_keeps_its_runs(self):
        self.assertFalse(history.path().exists())
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute(history.SCHEMA)
            db.execute(history.REVIEWS_SCHEMA)       # from before a review kept its round
            columns = ",".join(row[1] for row in db.execute("PRAGMA table_info(runs)"))
            db.execute("INSERT INTO runs (run_id, repo, reviewer) VALUES ('old', 'acme', 'reviewer')")
            before = db.execute(f"SELECT {columns} FROM runs WHERE run_id='old'").fetchone()
        self.review(self.loop())
        self.assertEqual(self.reviews(), [("judge-1", 0, 0, 0)])
        with closing(sqlite3.connect(history.path())) as db:
            self.assertEqual(db.execute(f"SELECT {columns} FROM runs WHERE run_id='old'").fetchone(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
