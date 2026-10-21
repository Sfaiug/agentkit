"""A reviewer never reads the author's account of its own work: neither the executor's nor a
fixer's summary, nor a seat's own PR description, reaches any reviewer prompt, while the
summaries stay on the record and a dispute ak records still reaches the reviewer."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
from fixtures.hand_in import scripted, stateful
from fixtures.own_pr import OwnPr
from agentkit import config, run, staffing, stop, transitions, turns, worker

CLAIM = "acme-claim"
WHY = "The task asks for it on."


class TaskRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-author-words-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": "",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name, value in (
                (worker, "auth_ok", (True, "fixture")), (worker, "marked_pids", []),
                (worker, "kill_marked", True), (stop, "marker_pids", []),
                (run.orch, "stop_scope", None), (turns, "note_turn_meters", None),
                (transitions, "history_role_tokens", None), (turns, "memory_cap_note", None),
                (run, "pickup_new_code", None), (run.history, "update_run", None)):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        config.ensure_dirs()
        self.cfg = config.load()
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "api.py").write_text("enabled = False\n")
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", "Existing behaviour")
        base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        self.directory = self.root / "run"
        self.directory.mkdir()
        self.plan = self.root / "plan.json"
        self.calls = self.root / "calls.jsonl"
        # each turn takes the next row: its edits, its hand-in commands, and what it says
        adapter = self.root / "adapter"
        body = f'''import json, os, pathlib, subprocess, sys
plan = pathlib.Path({str(self.plan)!r})
rows = json.loads(plan.read_text())
row = rows.pop(0)
plan.write_text(json.dumps(rows))
workspace = pathlib.Path(sys.argv[4])
for name, content in row.get("edits", {{}}).items():
    (workspace / name).write_text(content)
for args in row.get("commands", []) + [["done"]]:
    subprocess.run([sys.executable, {str(REPO / "bin/ak")!r}, "hand-in", *args],
                   capture_output=True, text=True)
with pathlib.Path({str(self.calls)!r}).open("a") as fh:
    fh.write(json.dumps({{"prompt": pathlib.Path(sys.argv[5]).read_text()}}) + "\\n")
out = pathlib.Path(sys.argv[6])
(out / "final.md").write_text(row.get("says", "## Findings\\n"))
(out / "session_id").write_text("fixture-session")
'''
        adapter.write_text(f"#!{sys.executable}\n{scripted(body)}")
        adapter.chmod(0o755)
        stateful(adapter, self.root, {m["harness"] for m in self.cfg["models"].values()})
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(self.root)}))
        self.stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        state = {"run_id": self.root.name, "title": "Author words fixture", "state": "running",
                 "base": "main", "base_sha": base, "branch": "ak/fix-api", "rounds": 2,
                 "executor": "opus", "reviewer": "astra", "round_summaries": [],
                 "repo": str(self.wt), "worktree": str(self.wt), "findings": ""}
        self.lp = run.Loop(self.cfg, self.directory, state, {}, lambda _: None, self.wt,
                           "# Enable the feature", ["true"], "context", [])

    def test_no_summary_reaches_a_reviewer_and_a_dispute_does(self):
        finding = ["finding", "api.py:1", "feature on by default", "task wants it off",
                   "--quote", "enabled = True"]
        self.plan.write_text(json.dumps([
            {"edits": {"api.py": "enabled = True\n"},
             "says": f"## Summary\nExecutor {CLAIM}: the feature works."},
            {"commands": [finding]},
            {"commands": [["dispute", "api.py:1", WHY, "--quote", "enabled = True"]],
             "says": f"## Summary\nFixer {CLAIM}: nothing to fix."},
            {}]))
        self.lp.rnd = 0
        run.rounds(self.lp)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 4)
        executor, first, fixer, second = (call["prompt"] for call in calls)
        self.assertIn("feature on by default", fixer)            # the fix answers the FAIL
        for prompt in (first, second):
            self.assertIn("## Diff", prompt)
            self.assertNotIn(CLAIM, prompt)
        self.assertIn(WHY, second)                          # the dispute ak recorded
        summaries = [row["summary"] for row in self.lp.state["round_summaries"]]
        self.assertIn(f"Executor {CLAIM}", summaries[0])
        self.assertIn(f"Fixer {CLAIM}", summaries[1])


class SeatsOwnPr(OwnPr):
    def test_no_fixer_summary_reaches_the_reviewer_of_a_seats_own_pr(self):
        self.fix_summary = f"## Summary\nFixer {CLAIM}: the fence holds."
        self.pr["body"] = f"## Summary\nAuthor {CLAIM}: every edge case is fixed."
        with patch.object(run, "ready_order", return_value=["astra", "opus"]), \
                patch.object(staffing, "ready_order", return_value=["astra", "opus"]):
            state = self.review(["FAIL", "PASS"])
        self.assertEqual([row["verdict"] for row in state["round_summaries"]], ["FAIL", "PASS"])
        self.assertEqual(len(self.prompts), 2)
        for prompt in self.prompts:
            self.assertIn("Review PR #7: Mend the fence", prompt)
            self.assertIn("by owner", prompt)
            self.assertNotIn(CLAIM, prompt)
        self.assertIn(f"Fixer {CLAIM}", state["round_summaries"][1]["summary"])
        self.assertIn(f"Author {CLAIM}", self.fixes[0])     # the fixer still reads the PR's words


if __name__ == "__main__":
    unittest.main()
