"""A reviewed run checks its rebased tree before joining; that pass answers the lander. Offline."""

from contextlib import contextmanager
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, deliver, gate, gitcall, land, record, roundloop, run, watch
from fixtures.sandbox import Sandbox
from test_merge_step import make_loop, make_repos

SUITE = 'python3 acme_suite.py "$AK_SHARD"'
ONCE = "echo acme-ready"


class SuiteBeforeLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        _, self.owner, self.wt = make_repos(self.root)
        self.lp, self.directory, _ = make_loop(config.RUNS, self.wt)
        self.lp.state["run_id"] = self.directory.name
        self.lp.write()
        (self.directory / "task.md").write_text(
            f"# Fix API\n\n## Done when\n```bash\ntrue\n{ONCE} # once\n```\n")
        self.reviewed = copy.deepcopy(self.lp.state["review"])
        (self.owner / "AGENTS.md").write_text(f"---\nusers: none\ntests: {SUITE}\n---\n")
        (self.owner / "target.txt").write_text("new target\n")
        run.git(self.owner, "add", ".")
        run.git(self.owner, "commit", "-m", "advance target and declare suite")
        run.git(self.owner, "push", "origin", "main")
        self.tip = run.git(self.owner, "rev-parse", "HEAD")
        self.turn = deliver.turn_path(self.lp, "origin/main")
        self.red, self.checks, self.turns = False, [], []
        self.stack.enter_context(patch.object(gate, "gate_turn", side_effect=self.heavy_turn))
        self.stack.enter_context(patch.object(gate, "run_done_when", side_effect=self.check))
        self.stack.enter_context(patch.object(land, "_code", return_value="acme-checker"))
        self.stack.enter_context(patch.object(land, "start_line"))
        self.stack.enter_context(patch.object(watch, "launch_resume"))
        self.stack.enter_context(patch.object(deliver, "rights", return_value=("acme/widget", "WRITE")))
        which = deliver.shutil.which
        self.stack.enter_context(patch.object(deliver.shutil, "which", side_effect=lambda name, **kw:
                                             "/fixture/gh" if name == "gh" else which(name, **kw)))
        self.stack.enter_context(patch.object(deliver, "merge_lock", side_effect=AssertionError("delivery lock")))
        self.stack.enter_context(patch.object(deliver, "push", side_effect=AssertionError("push")))

    @contextmanager
    def heavy_turn(self, directory, log_path, log, command=None, cwd=None, **_kw):
        self.turns.append((directory, command))
        self.assertEqual(directory, self.directory)
        self.assertEqual(command, SUITE)
        self.assertTrue(record.read_state(directory)["landing"])
        yield

    def check(self, cmds, cwd, log_path, *_args, marks=None, pieces=None, **kw):
        if SUITE not in cmds:
            return True, "$ true\n[exit 0]\n"
        self.assertEqual(list(cmds), [ONCE, SUITE])
        self.assertTrue(kw["heavy"])
        self.assertTrue(roundloop.integrated(cwd, self.tip))
        self.assertEqual((cwd / "target.txt").read_text(), "new target\n")
        self.assertFalse(land.line(self.turn))
        self.assertTrue(self.turns)
        tree = run.git(cwd, "rev-parse", "HEAD^{tree}")
        self.assertNotEqual(tree, self.reviewed["tree_sha"])
        self.checks.append(tree)
        marks.extend([0, int(self.red)])
        pieces[SUITE] = {"1/2": int(self.red), "2/2": 0}
        return not self.red, f"$ {SUITE}\n[exit {int(self.red)}]\n" + (
            "ERROR: acme regression\n" if self.red else "acme passed\n")

    def test_red_never_joins_and_takes_its_landing_fixer(self):
        self.red = True

        def fix(lp, upstream, text):
            self.assertEqual(upstream, "origin/main")
            self.assertEqual(lp.state["landing_reds"], 1)
            self.assertTrue(roundloop.integrated(lp.wt, self.tip))
            self.assertIn("acme regression", text)
            self.assertFalse(land.line(self.turn))
            return False

        with patch.object(roundloop, "fix_final_check", side_effect=fix) as fixer:
            self.assertFalse(deliver.merge(self.lp))
        fixer.assert_called_once()
        self.assertEqual(self.checks, [run.git(self.wt, "rev-parse", "HEAD^{tree}")])
        self.assertEqual(self.lp.state["landing_reds"], 1)
        self.assertNotIn("waiting_on", record.read_state(self.directory))
        self.assertIsNone(land.passed(self.turn, self.checks[0]))

    def test_green_joins_with_evidence_and_its_one_member_stack_needs_no_check(self):
        self.assertFalse(deliver.merge(self.lp))
        saved = record.read_state(self.directory)
        tree = self.checks[0]
        self.assertEqual(saved["target_sha"], self.tip)
        self.assertEqual(saved["review"]["tree_sha"], tree)
        self.assertEqual(saved["waiting_on"]["line"], self.turn.name)
        self.assertNotIn("landing", saved)
        self.assertEqual(land.passed(self.turn, tree)["tested"], tree)
        self.assertEqual(land.passed(self.turn, tree)["checks"], [ONCE, SUITE])
        with patch.object(record, "process_active", return_value=False):
            land.check_line(self.turn)
        self.assertEqual(record.read_state(self.directory)["waiting_on"]["land"], tree)
        self.assertEqual(self.checks, [tree])
        self.assertEqual(self.turns, [(self.directory, SUITE)])

    def test_a_fixed_red_is_reviewed_and_checks_again_before_joining(self):
        self.red = True

        def execute(lp, role, text, name):
            self.assertEqual((role, name), ("fixer", "final-fixer"))
            self.assertFalse(land.line(self.turn))
            self.assertIn("acme regression", text)
            (lp.wt / "work.txt").write_text("fixed\n")
            run.git(lp.wt, "add", ".")
            run.git(lp.wt, "commit", "-m", "fix regression")
            self.red = False
            return "## Summary\nFixed regression."

        def review(lp, summary, ok, text, reason, **kw):
            self.assertTrue(ok)
            self.assertFalse(kw["record"])
            self.assertFalse(land.line(self.turn))
            lp.state["review"].update(gitcall.commit_identity(lp.wt))
            lp.state.pop("review_pending", None)
            lp.write()
            return "PASS"

        with patch.object(roundloop, "execute", side_effect=execute) as fixer, \
                patch.object(roundloop, "review", side_effect=review) as reviewer:
            self.assertFalse(deliver.merge(self.lp))
        fixer.assert_called_once()
        reviewer.assert_called_once()
        self.assertEqual(len(self.checks), 2)
        self.assertNotEqual(*self.checks)
        self.assertIsNone(land.passed(self.turn, self.checks[0]))
        self.assertEqual(land.passed(self.turn, self.checks[1])["tested"], self.checks[1])
        self.assertIn("line", self.lp.state["waiting_on"])
        self.assertEqual(self.lp.state["landing_reds"], 1)
        self.assertEqual(len(self.lp.state["round_summaries"]), 1)


if __name__ == "__main__":
    unittest.main()
