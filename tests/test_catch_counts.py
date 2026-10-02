"""Finished, weighed reviews reach history and the model's own screen under a test HOME."""

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
from agentkit import config, hand_in, history, menu, run, terminal, worker


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
        for module, name in ((worker, "kill_marked"), (run, "memory_cap_note"),
                             (run, "history_role_tokens")):
            self.stack.enter_context(patch.object(module, name, return_value=None))
        self.cfg = {"models": {}, "providers": {"acme": {}, "beta": {}},
                    "defaults": {"orchestrator": "builder", "workers": ["builder"],
                                 "reviewers": ["reviewer", "spare"]}}
        for name, harness, model, provider in (
                ("builder", "test", "build-1", "acme"),
                ("reviewer", "test", "judge-1", "beta"),
                ("alias", "test", "judge-1", "beta"),
                ("other-harness", "other", "judge-1", "beta"),
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
                      "Review the API.", ["true"], "", [])
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
        with patch.object(run, "call_retrying", side_effect=self.turn(list(rows))):
            return run.review(lp, "API fixed.", True, "$ true\n[exit 0]\n", record=record)

    def screen(self, name="reviewer", width=120):
        with patch.object(terminal, "layout_width", return_value=width):
            return menu.model_body(self.cfg, name)

    def assert_counts(self, reviewed, caught, already, unproven, name="reviewer"):
        self.assertIn(f"  Reviewed {reviewed} time{'s' if reviewed != 1 else ''} · caught {caught} · "
                      f"{already} already on main · {unproven} unproven", self.screen(name)[0])

    def assert_unused(self, name="reviewer"):
        self.assertIn("  Not used as a reviewer yet", self.screen(name)[0])

    def test_weighed_counts_reach_the_database_and_model_screen(self):
        lp = self.loop()
        self.assertEqual(self.review(lp, self.records()), "FAIL")
        self.assert_counts(1, 1, 1, 1)
        with closing(sqlite3.connect(history.path())) as db:
            rows = db.execute("SELECT run_id, harness, model, blocking, followup, note "
                              "FROM reviews").fetchall()
        self.assertEqual(rows, [("fix-api", "test", "judge-1", 1, 1, 1)])
        self.assertEqual(history.path(), self.root / ".agentkit/history.db")
        # The run row changes reviewer; its earlier review still belongs to judge-1.
        lp.rnd = 2
        lp.reviewer = "spare"
        self.assertEqual(self.review(lp), "PASS")
        run.history_finish({**lp.state, "state": "pass"})
        self.assert_counts(1, 1, 1, 1)
        self.assert_counts(1, 0, 0, 0, "spare")
        self.assert_unused("builder")

    def test_a_clean_landing_review_counts_without_spending_a_round(self):
        lp = self.loop()
        self.assertEqual(self.review(lp, self.records()), "FAIL")
        self.assertEqual(self.review(lp, record=False), "PASS")
        self.assertEqual(len(lp.state["round_summaries"]), 1)
        for _ in range(2):
            run.history_finish({**lp.state, "state": "pass"})
        self.assert_counts(2, 1, 1, 1)

    def test_the_model_id_step_and_aliases_read_the_identity_that_ran(self):
        lp = self.loop()
        self.review(lp, self.records())
        self.assert_counts(1, 1, 1, 1, "alias")
        self.assert_unused("other-harness")
        catalog = [{"id": model, "efforts": ["high"]} for model in ("judge-1", "judge-2")]
        with patch.object(menu, "_offered", return_value=catalog):
            self.assertEqual(menu.config_model_id(self.cfg, "reviewer", 1, ()), "")
            self.assert_unused()
            self.review(lp)
            self.assert_counts(1, 0, 0, 0)
            self.assertEqual(menu.config_model_id(self.cfg, "reviewer", -1, ()), "")
        self.assert_counts(1, 1, 1, 1)

    def test_suite_and_stopped_runs_never_contribute(self):
        for name, fields in (("smoke", {"repo": str(self.root / "agentkit-smoke")}),
                             ("temporary", {"repo": str(config.TMP / "clone/acme")}),
                             ("sink", {"notify_sink": "fixture"})):
            with self.subTest(name=name):
                lp = self.loop(name, **fields)
                self.review(lp)
                self.assert_unused()
        lp = self.loop("stopped")
        self.review(lp, self.records())
        self.assert_counts(1, 1, 1, 1)
        run.history_finish({**lp.state, "state": "stopped"})
        self.assert_unused()
        # Old suite rows can have only the basename in SQLite; REAL_WORK reads run.json.
        lp = self.loop("old-suite")
        self.review(lp, self.records())
        lp.state["repo"] = str(config.TMP / "clone/acme")
        lp.save()
        self.assert_unused()

    def test_an_unfinished_reviewer_contributes_nothing(self):
        lp = self.loop()
        call = self.turn(self.records(), done=False)

        def extra(*args, **kwargs):
            return (*call(*args, **kwargs), False)

        with patch.object(run, "call_retrying", side_effect=call), \
                patch.object(worker, "turn", side_effect=extra), \
                patch.object(run, "collect_usage", return_value={}), \
                patch.object(run, "ready_order", return_value=[]):
            with self.assertRaises(run.Exhausted):
                run.review(lp, "API fixed.", True, "$ true\n[exit 0]\n")
        self.assert_unused()

    def test_phone_wraps_the_plain_line_and_keeps_only_the_three_action_rows(self):
        self.review(self.loop(), self.records())
        lines, places = self.screen(width=40)
        self.assertEqual([row for row, _ in places.values()], list(menu.MODEL_ROWS))
        self.assertGreater(len(lines), 4)
        self.assertEqual(lines[3], "")
        self.assertEqual(" ".join(line.strip() for line in lines[4:]),
                         "Reviewed 1 time · caught 1 · 1 already on main · 1 unproven")
        for line in lines:
            self.assertLessEqual(terminal.cells(line), 40, line)

    def test_an_old_database_and_missing_history_read_as_unused(self):
        self.assert_unused()
        self.assertFalse(history.path().exists())
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute(history.SCHEMA)
            db.execute("INSERT INTO runs (run_id, repo, reviewer) VALUES ('old', 'acme', 'reviewer')")
            before = db.execute("SELECT * FROM runs WHERE run_id='old'").fetchone()
        self.assert_unused()
        self.review(self.loop())
        self.assert_counts(1, 0, 0, 0)
        with closing(sqlite3.connect(history.path())) as db:
            self.assertEqual(db.execute("SELECT * FROM runs WHERE run_id='old'").fetchone(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
