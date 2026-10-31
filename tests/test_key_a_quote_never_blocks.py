"""A quote never blocks: only a failing command decides what the fixer must answer.

A reviewer's `finding --quote` shows where to look; whether it matters is a test's to say, so
ak weighs it as a note, on an added line as anywhere: the round passes with the note in Notes.
A check line the change removed is proven like any defect: `grep -qF` for it fails while the
line is gone, and that finding blocks.  Offline: a real git repository, the executor's change
committed on its branch, and a reviewer scripted to hand in.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, handback, run, stop, transitions, turns, worker
from fixtures.hand_in import scripted, stateful

CHECK = "assert total(-1, 1) == 0"
ADDED = 'print("negatives skipped")'


class AQuoteNeverBlocks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-quote-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(account_home(self.root))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "", "PYTHONPYCACHEPREFIX": "", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name, value in (
                (worker, "auth_ok", (True, "fixture")), (worker, "marked_pids", []),
                (worker, "kill_marked", True), (stop, "marker_pids", []), (run.orch, "stop_scope", None),
                (turns, "note_turn_meters", None), (transitions, "history_role_tokens", None),
                (turns, "memory_cap_note", None), (run.history, "update_run", None)):
            stack.enter_context(patch.object(module, name, return_value=value))
        config.ensure_dirs()
        cfg = config.load()
        wt = self.root / "acme"
        (wt / "tests").mkdir(parents=True)
        run.git(wt, "init", "-qb", "main")
        run.git(wt, "config", "user.name", "Fixture")
        run.git(wt, "config", "user.email", "fixture@example.invalid")
        (wt / "api.py").write_text("def total(a, b):\n    return a + b\n")
        (wt / "tests/test_api.py").write_text(f"from api import total\nassert total(2, 2) == 4\n{CHECK}\n")
        self.commit(wt, "Totals and their check")
        base = run.git(wt, "rev-parse", "HEAD")
        # the executor's change: the negative check gives way to a line of its own
        run.git(wt, "checkout", "-qb", "ak/fix-api")
        (wt / "tests/test_api.py").write_text(f"from api import total\nassert total(2, 2) == 4\n{ADDED}\n")
        self.commit(wt, "Skip negatives")
        self.plan = self.root / "plan.json"
        adapter = self.root / "adapter"
        adapter.write_text(f"#!{sys.executable}\n" + scripted(f'''import json, pathlib, subprocess, sys
for args in json.loads(pathlib.Path({str(self.plan)!r}).read_text()) + [["done"]]:
    subprocess.run([sys.executable, {str(REPO / "bin/ak")!r}, "hand-in", *args], check=True)
out = pathlib.Path(sys.argv[6])
(out / "final.md").write_text("Handed in.")
(out / "session_id").write_text("fixture-session")
'''))
        adapter.chmod(0o755)
        stateful(adapter, self.root, {m["harness"] for m in cfg["models"].values()})
        stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(self.root)}))
        stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        state = {"run_id": "quote-fixture", "title": "Skip negatives", "state": "running", "base": "main",
                 "base_sha": base, "branch": "ak/fix-api", "rounds": 3, "executor": "opus",
                 "reviewer": "astra", "round_summaries": [], "repo": str(wt), "worktree": str(wt)}
        self.lp = run.Loop(cfg, self.root / "run", state, {}, lambda _: None, wt,
                           "# Fixture", ["true"], "context")
        self.lp.run_dir.mkdir()
        self.lp.rnd = 1
        self.lp.validation = run.commit_identity(wt)

    @staticmethod
    def commit(wt, message):
        run.git(wt, "add", ".")
        run.git(wt, "commit", "-qm", message)

    def review(self, *evidence):
        """One round: the reviewer finds the negative check gone, on the line added in its place."""
        self.plan.write_text(json.dumps([["finding", "tests/test_api.py:3", "the negative check is gone",
                                          "negative totals go unchecked", *evidence]]))
        return run.review(self.lp, "## Summary\nFixture", True, "$ true\n[exit 0]")

    def test_a_quote_on_an_added_line_is_a_note_and_the_round_passes(self):
        self.assertEqual(self.review("--quote", ADDED), "PASS")
        self.assertEqual(self.lp.state["round_summaries"][-1]["finding_count"], 0)
        self.assertFalse(handback.review_failed(self.lp.state))
        self.assertEqual(self.lp.state["followups"], [])
        [note] = self.lp.state["notes"]
        self.assertIn("tests/test_api.py:3 - the negative check is gone", note)
        self.assertIn(ADDED, note)
        self.assertIn("## Notes\n- tests/test_api.py:3 - the negative check is gone",
                      Path(self.lp.state["findings_file"]).read_text())

    def test_the_removed_check_line_proven_by_a_command_blocks(self):
        grep = f"grep -qF '{CHECK}' tests/test_api.py"
        self.assertEqual(self.review("--run", grep), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][-1]["finding_count"], 1)
        self.assertTrue(handback.review_failed(self.lp.state))
        [row] = [row for row in self.lp.state["review_records"] if row["kind"] == "finding"]
        self.assertEqual((row["path"], row["line"], row["evidence"]["run"]), ("tests/test_api.py", 3, grep))
        self.assertEqual(self.lp.state["notes"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
