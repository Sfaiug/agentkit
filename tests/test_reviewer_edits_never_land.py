"""A reviewer's edits are archived, then undone before any next turn or round."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker


ADAPTER = '''import json, os, pathlib, subprocess, sys
assert sys.argv[1] == "run", sys.argv
root = pathlib.Path(os.environ["REVIEW_FIXTURE"])
wt, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
def git(*args):
    return subprocess.check_output(["git", "-C", str(wt), *args], text=True).strip()
if (git("rev-parse", "HEAD") != (root / "head").read_text()
        or (wt / "tracked.txt").read_text() != "executor work\\n"
        or (wt / "keep/existing.txt").read_text() != "suite artifact\\n"
        or sorted(git("ls-files", "--others", "--exclude-standard").splitlines()) != ["keep/existing.txt"]):
    (out / "final.md").write_text("VERDICT: FAIL\\n## Findings\\nThe previous turn's edits remain.")
    sys.exit(0)
plan = json.loads((root / "responses.json").read_text())
row = plan.pop(0)
(root / "responses.json").write_text(json.dumps(plan))
for name, content in row.get("files", {}).items():
    path = wt / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes.fromhex(content) if isinstance(content, str) and name.endswith(".bin")
                     else content.encode())
if row.get("stage") or row.get("commit"):
    git("add", "--", *row["files"])
if row.get("commit"):
    git("commit", "-q", "-m", "reviewer commit")
if row.get("empty_commit"):
    git("commit", "-q", "--allow-empty", "-m", "reviewer empty commit")
(out / "final.md").write_text(row.get("text", "VERDICT: PASS"))
(out / "stderr.log").write_text(row.get("stderr", ""))
(out / "session_id").write_text("fixture-session")
sys.exit(row.get("code", 0))
'''


class ReviewerEdits(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-reviewer-edits-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "REVIEW_FIXTURE": str(self.root),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        cfg = config.load()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        for harness in {entry["harness"] for entry in cfg["models"].values()}:
            adapter = adapters / f"{harness}.sh"
            adapter.write_text(f"#!{sys.executable}\n{ADAPTER}")
            adapter.chmod(0o755)
        self.stack.enter_context(patch.object(worker, "auth_ok", return_value=(True, "")))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(run.usage, "account", return_value=(None, True)))
        self.stack.enter_context(patch.object(run, "transient_wait"))
        self.stack.enter_context(patch.object(run, "memory_cap_note"))
        self.stack.enter_context(patch.object(run, "note_turn_meters"))
        self.stack.enter_context(patch.object(run, "history_role_tokens"))
        self.wt = self.root / "acme"
        self.wt.mkdir()
        self.git("init", "-q", "-b", "ak/fix-api")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        (self.wt / "tracked.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        base = self.git("rev-parse", "HEAD")
        (self.wt / "tracked.txt").write_text("executor work\n")
        self.git("commit", "-qam", "executor work")
        self.head = self.git("rev-parse", "HEAD")
        (self.root / "head").write_text(self.head)
        (self.wt / "keep").mkdir()
        (self.wt / "keep/existing.txt").write_text("suite artifact\n")
        directory = config.RUNS / "fixture"
        (directory / "round-1").mkdir(parents=True)
        state = {"run_id": "fixture", "state": "running", "base": "main", "base_sha": base,
                 "rounds": 3, "round_summaries": [], "executor": "opus", "reviewer": "astra"}
        self.logs = []
        self.lp = run.Loop(cfg, directory, state, {}, self.logs.append, self.wt,
                           "Review the change.", ["true"], "", ["spark"])
        self.lp.rnd = 1
        self.lp.validation = run.commit_identity(self.wt)
        self.lp.artifacts.add("keep/existing.txt")
        self.archive = self.lp.round_dir / "reviewer-changes.patch"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.wt), *args], text=True).strip()

    def review(self, *responses):
        (self.root / "responses.json").write_text(json.dumps(responses))
        return run.review(self.lp, "Executor work.", True, "$ true\n[exit 0]\n")

    def assert_restored(self):
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual((self.wt / "tracked.txt").read_text(), "executor work\n")
        self.assertEqual(run.dirty_paths(self.wt), ["keep/existing.txt"])
        self.assertEqual((self.wt / "keep/existing.txt").read_text(), "suite artifact\n")
        run.commit_leftovers(self.wt, self.logs.append, self.lp.artifacts)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head)

    def test_new_file_never_reaches_next_round(self):
        self.assertEqual(self.review({"files": {"keep/reviewer.txt": "reviewer file\n"},
                                      "text": "VERDICT: FAIL"}), "FAIL")
        run.commit_leftovers(self.wt, self.logs.append, self.lp.artifacts)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.head,
                         "the next round committed the reviewer's untracked file")
        self.assert_restored()
        self.assertIn("+reviewer file", self.archive.read_text())
        self.assertNotIn("suite artifact", self.archive.read_text())
        self.assertTrue(any("WARN" in line and "keep/reviewer.txt" in line for line in self.logs))

    def test_tracked_staged_and_committed_edits_are_archived_and_undone(self):
        for mode in ({}, {"stage": True}, {"commit": True}):
            with self.subTest(mode=mode):
                row = {"files": {"tracked.txt": "reviewer edit\n", "new.txt": "reviewer new\n",
                                 "new.bin": "000102ff"}, **mode}
                self.assertEqual(self.review(row), "PASS")
                self.assert_restored()
                saved = self.archive.read_text()
                self.assertIn("+reviewer edit", saved)
                self.assertIn("+reviewer new", saved)
                self.assertIn("GIT binary patch", saved)
                self.assertTrue(any("WARN" in line and "tracked.txt" in line for line in self.logs))

    def test_transport_retry_restores_before_the_next_adapter_call(self):
        self.assertEqual(self.review(
            {"files": {"tracked.txt": "first edit\n"}, "commit": True,
             "code": 1, "text": "", "stderr": "HTTP 503 Service Unavailable"},
            {"files": {"retry.txt": "retry edit\n"}}), "PASS")
        self.assert_restored()
        self.assertIn("+first edit", self.archive.read_text())
        self.assertIn("+retry edit", self.archive.read_text())
        self.assertEqual(json.loads((self.root / "responses.json").read_text()), [])

    def test_no_verdict_ask_restores_both_turns(self):
        self.assertEqual(self.review(
            {"files": {"tracked.txt": "silent edit\n"}, "commit": True,
             "text": "Still reviewing."},
            {"files": {"asked.txt": "extra ask edit\n"}, "stage": True}), "PASS")
        self.assert_restored()
        self.assertIn("+silent edit", self.archive.read_text())
        self.assertIn("+extra ask edit", self.archive.read_text())

    def test_foreground_retry_restores_before_the_next_adapter_call(self):
        self.assertEqual(self.review(
            {"files": {"tracked.txt": "background edit\n"},
             "stderr": "Background tasks still running"},
            {"files": {"foreground.txt": "foreground edit\n"}}), "PASS")
        self.assert_restored()
        self.assertIn("+background edit", self.archive.read_text())
        self.assertIn("+foreground edit", self.archive.read_text())

    def test_existing_dirty_files_are_restored_even_if_the_reviewer_commits_them(self):
        self.assertEqual(self.review(
            {"files": {"keep/existing.txt": "reviewer artifact edit\n",
                       "keep/new.txt": "reviewer new\n"}, "commit": True}), "PASS")
        self.assert_restored()
        self.assertIn("+reviewer artifact edit", self.archive.read_text())

    def test_fallback_reviewer_starts_on_the_executor_commit(self):
        with patch.object(run, "collect_usage", return_value={}), \
                patch.object(run, "ready_order", return_value=["spark"]):
            self.assertEqual(self.review(
                {"files": {"tracked.txt": "broken turn edit\n"}, "commit": True,
                 "code": 1, "text": "", "stderr": "codex is not installed"},
                {"files": {"spare.txt": "spare edit\n"}}), "PASS")
        self.assert_restored()
        self.assertIn("+broken turn edit", self.archive.read_text())
        self.assertIn("+spare edit", self.archive.read_text())

    def test_exception_still_restores_the_checkout(self):
        real_call = worker.call

        def stopped(*args, **kwargs):
            real_call(*args, **kwargs)
            raise run.Stopped("fixture stop")

        with patch.object(worker, "call", side_effect=stopped):
            with self.assertRaisesRegex(run.Stopped, "fixture stop"):
                self.review({"files": {"tracked.txt": "stopped edit\n", "stopped.txt": "new\n"},
                             "commit": True})
        self.assert_restored()
        self.assertIn("+stopped edit", self.archive.read_text())

    def test_empty_commit_is_undone_and_named(self):
        self.assertEqual(self.review({"empty_commit": True}), "PASS")
        self.assert_restored()
        self.assertIn(self.head, self.archive.read_text())
        self.assertTrue(any("WARN" in line and "commit" in line for line in self.logs))

    def test_read_only_review_needs_no_archive_or_cleanup_warning(self):
        self.assertEqual(self.review({}), "PASS")
        self.assert_restored()
        self.assertFalse(self.archive.exists())
        self.assertFalse(any("WARN" in line for line in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
