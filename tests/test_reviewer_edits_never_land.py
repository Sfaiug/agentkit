"""A reviewer's edits are archived, then undone before any next turn or round."""

from contextlib import ExitStack, chdir, contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker


ADAPTER = '''import json, os, pathlib, subprocess, sys, time
assert sys.argv[1] == "run", sys.argv
root = pathlib.Path(os.environ["REVIEW_FIXTURE"])
wt, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
def git(*args):
    return subprocess.check_output(["git", "-C", str(wt), *args], text=True).strip()
if (git("rev-parse", "HEAD") != (root / "head").read_text()
        or (wt / "tracked.txt").read_text() != "executor work\\n"
        or (wt / "keep/existing.txt").read_text() != "suite artifact\\n"
        or sorted(p for p in git("ls-files", "--others", "--exclude-standard").splitlines()
                  if p != "report.txt") != ["keep/existing.txt"]):
    (out / "final.md").write_text("VERDICT: FAIL\\n## Findings\\nThe previous turn's edits remain.")
    sys.exit(0)
plan = json.loads((root / "responses.json").read_text())
row = plan.pop(0)
(root / "responses.json").write_text(json.dumps(plan))
if row.get("signal"):
    (root / row["signal"]).touch()
if row.get("wait"):
    deadline = time.monotonic() + 5
    while not (root / row["wait"]).exists():
        if time.monotonic() >= deadline:
            (out / "final.md").write_text("VERDICT: FAIL\\nTimed out waiting for the fixture suite.")
            sys.exit(0)
        time.sleep(0.01)
for args in row.get("git", []):
    git(*args)
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
if row.get("push"):
    pushed = subprocess.run(["git", "-C", str(wt), "push"], capture_output=True, text=True)
    (out / "push.json").write_text(json.dumps({"code": pushed.returncode,
                                              "stderr": pushed.stderr}))
for name, mode in row.get("chmod", {}).items():
    (wt / name).chmod(mode)
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

    def suite_files_case(self, no_verdict):
        self.lp.once = ["test -f report.txt"]
        finished = threading.Event()
        real_join = run.join_suite

        def suite(cmds, cwd, log_path, *args, **_kw):
            deadline = time.monotonic() + 5
            while not (self.root / "review-started").exists():
                if time.monotonic() >= deadline:
                    raise AssertionError("the reviewer never started")
                time.sleep(0.01)
            report = Path(cwd) / "report.txt"
            report.write_text("coverage\n")
            (self.root / "suite-ready").touch()
            if not finished.wait(5):
                raise AssertionError("the reviewer never finished")
            ok = report.exists() and report.read_text() == "coverage\n"
            text = f"$ {cmds[0]}\n[exit {0 if ok else 1}]\n"
            Path(log_path).write_text(text)
            self.lp.artifacts.add("report.txt")
            return ok, text

        def join(lp):
            finished.set()
            return real_join(lp)

        rows = [{"signal": "review-started", "wait": "suite-ready",
                 "text": "Still reviewing." if no_verdict else "VERDICT: PASS"}]
        if no_verdict:
            rows.append({})
        with patch.object(run, "run_done_when", side_effect=suite), \
                patch.object(run, "join_suite", side_effect=join):
            self.lp.suite_thread, self.lp.suite_box = run.start_suite(self.lp)
            thread = self.lp.suite_thread
            try:
                verdict = self.review(*rows)
            finally:
                finished.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(verdict, "PASS", self.logs)
        self.assertTrue(self.lp.once_ok)
        self.assertEqual((self.wt / "report.txt").read_text(), "coverage\n")
        self.assertFalse(self.archive.exists())
        self.assertFalse(any("WARN" in line for line in self.logs), self.logs)

    def test_live_suite_files_survive_a_read_only_reviewer(self):
        self.suite_files_case(False)

    def test_live_suite_files_survive_the_extra_verdict_ask(self):
        self.suite_files_case(True)

    def test_suite_files_disappearing_during_copy_do_not_abort_review(self):
        build = self.wt / "build"
        build.mkdir()
        (build / "input.o").write_text("existing build input\n")
        with (self.wt / ".git/info/exclude").open("a") as excluded:
            excluded.write("\nbuild/\n")
        real_call = worker.call

        def check_input(cfg, name, body, workspace, out, role, session, **kwargs):
            self.assertEqual((Path(workspace) / "build/input.o").read_text(),
                             "existing build input\n")
            return real_call(cfg, name, body, workspace, out, role, session, **kwargs)

        for directory in (False, True):
            with self.subTest(directory=directory):
                transient = build / "transient"
                if directory:
                    transient.mkdir()
                    (transient / "output.o").touch()
                    real_scandir = os.scandir

                    def vanished(path):
                        if not isinstance(path, int) and Path(path) == transient:
                            (transient / "output.o").unlink()
                            transient.rmdir()
                        return real_scandir(path)

                    deleting = patch.object(os, "scandir", side_effect=vanished)
                else:
                    transient.touch()
                    real_copyfile = run.shutil.copyfile

                    def vanished(src, dst, *args, **kwargs):
                        if Path(src) == transient:
                            transient.unlink()
                        return real_copyfile(src, dst, *args, **kwargs)

                    deleting = patch.object(run.shutil, "copyfile", side_effect=vanished)
                with deleting, patch.object(worker, "call", side_effect=check_input):
                    self.assertEqual(self.review({}), "PASS")
                self.assertFalse(transient.exists())
                self.assert_restored()
                self.assertFalse(self.archive.exists())
                self.assertFalse(any("WARN" in line for line in self.logs), self.logs)

    def test_special_and_unreadable_files_do_not_abort_review(self):
        artifacts = self.wt / "tmp"
        artifacts.mkdir()
        with (self.wt / ".git/info/exclude").open("a") as excluded:
            excluded.write("\ntmp/\n")
        (artifacts / "input.txt").write_text("review input\n")
        for name, target in (("file.link", "input.txt"), ("dir.link", "."),
                             ("broken.link", "missing")):
            (artifacts / name).symlink_to(target)
        real_call, real_copyfile = worker.call, run.shutil.copyfile

        for name in ("server.sock", "events.fifo", "private.txt"):
            with self.subTest(name=name):
                skipped = artifacts / name
                if name.endswith(".sock"):
                    # A relative bind stays under the UNIX socket pathname limit.
                    with chdir(artifacts), socket.socket(socket.AF_UNIX) as sock:
                        sock.bind(name)
                elif name.endswith(".fifo"):
                    os.mkfifo(skipped)
                else:
                    skipped.write_text("unreadable\n")
                    skipped.chmod(0)

                def copyfile(src, dst, *args, **kwargs):
                    # Inject the denial so the test also works when run as root.
                    if Path(src) == skipped and name == "private.txt":
                        raise PermissionError(f"cannot read {src}")
                    return real_copyfile(src, dst, *args, **kwargs)

                def check_input(cfg, model, body, workspace, out, role, session, **kwargs):
                    copied = Path(workspace) / "tmp"
                    self.assertFalse((copied / name).exists())
                    self.assertEqual((copied / "input.txt").read_text(), "review input\n")
                    for link, target in (("file.link", "input.txt"), ("dir.link", "."),
                                         ("broken.link", "missing")):
                        self.assertTrue((copied / link).is_symlink())
                        self.assertEqual(os.readlink(copied / link), target)
                    return real_call(cfg, model, body, workspace, out, role, session, **kwargs)

                try:
                    with patch.object(run.shutil, "copyfile", side_effect=copyfile), \
                            patch.object(worker, "call", side_effect=check_input):
                        self.assertEqual(self.review({"files": {"probe.txt": "reviewer edit\n"}}),
                                         "PASS")
                    self.assertTrue(any("WARN" in line and str(skipped) in line
                                        for line in self.logs), self.logs)
                    self.assertTrue(skipped.exists())
                    self.assertIn("+reviewer edit", self.archive.read_text())
                    self.assert_restored()
                finally:
                    if name == "private.txt":
                        skipped.chmod(0o600)
                    skipped.unlink()

    def test_read_only_cache_does_not_block_the_next_turn(self):
        cache = self.wt / "cache/mod"
        cache.mkdir(parents=True)
        (cache / "go.mod").write_text("module acme\n")
        cache.chmod(0o555)
        self.addCleanup(cache.chmod, 0o755)
        with (self.wt / ".git/info/exclude").open("a") as excluded:
            excluded.write("\ncache/\n")
        stale = self.lp.round_dir / "review-checkout/cache/mod"
        stale.mkdir(parents=True)
        (stale / "go.mod").write_text("stale copy\n")
        stale.chmod(0)
        real_call = worker.call

        def check_cache(cfg, name, body, workspace, out, role, session, **kwargs):
            self.assertEqual((Path(workspace) / "cache/mod/go.mod").read_text(), "module acme\n")
            return real_call(cfg, name, body, workspace, out, role, session, **kwargs)

        with patch.object(worker, "call", side_effect=check_cache):
            self.assertEqual(self.review({"text": "Still reviewing."}, {}), "PASS")
            self.assertEqual(self.review({"code": 1, "text": "",
                                          "stderr": "HTTP 503 Service Unavailable"}, {}), "PASS")
            self.assertEqual(self.review({}), "PASS")
        self.assertEqual(cache.stat().st_mode & 0o777, 0o555)
        self.assertEqual((cache / "go.mod").read_text(), "module acme\n")
        self.assertFalse((self.lp.round_dir / "review-checkout").exists())
        self.assert_restored()

    def test_read_only_reviewer_directories_are_archived_and_removed(self):
        self.assertEqual(self.review(
            {"files": {"probe/go.mod": "module acme\n"}, "chmod": {"probe": 0o555},
             "text": "Still reviewing."}, {}), "PASS")
        self.assertIn("+module acme", self.archive.read_text())
        self.assertTrue(any("WARN" in line and "probe" in line for line in self.logs), self.logs)
        self.assertEqual(json.loads((self.root / "responses.json").read_text()), [])
        self.assertFalse((self.lp.round_dir / "review-checkout").exists())
        self.assert_restored()

    @unittest.skipIf(os.geteuid() == 0, "root can read mode-000 files")
    def test_unreadable_reviewer_files_are_skipped_without_losing_the_verdict(self):
        for name in ("secret.txt", "tracked.txt", "keep/existing.txt"):
            with self.subTest(name=name):
                self.logs.clear()
                files = {name: "unreadable edit\n"}
                if name != "secret.txt":
                    files["readable.txt"] = "readable edit\n"
                self.assertEqual(self.review(
                    {"files": files,
                     "chmod": {name: 0}, "text": "Still reviewing."}, {}), "PASS")
                saved = self.archive.read_text()
                if name != "secret.txt":
                    self.assertIn("+readable edit", saved)
                self.assertIn(name, saved)
                self.assertTrue(any("WARN" in line and "skipped" in line and name in line
                                    for line in self.logs), self.logs)
                self.assertEqual(json.loads((self.root / "responses.json").read_text()), [])
                self.assertFalse((self.lp.round_dir / "review-checkout").exists())
                self.assert_restored()

    @unittest.skipIf(os.geteuid() == 0, "root can read mode-000 files")
    def test_initial_snapshot_skips_unreadable_dirty_files(self):
        real_changes = run.reviewer_changes

        @contextmanager
        def unreadable(wt, out, log, **_kw):
            dirty = Path(wt) / "keep/existing.txt"
            dirty.chmod(0)
            with real_changes(wt, out, log):
                dirty.chmod(0o644)
                yield

        with patch.object(run, "reviewer_changes", side_effect=unreadable):
            self.assertEqual(self.review({}), "PASS")
        self.assertIn("keep/existing.txt", self.archive.read_text())
        self.assertTrue(any("WARN" in line and "skipped" in line and "keep/existing.txt" in line
                            for line in self.logs), self.logs)
        self.assertFalse((self.lp.round_dir / "review-checkout").exists())
        self.assert_restored()

    def test_plain_reviewer_push_cannot_change_shared_refs(self):
        base = self.git("rev-parse", "HEAD~1")
        self.git("branch", "ak/landed", base)
        self.git("update-ref", "refs/remotes/origin/main", base)
        real_call = worker.call
        expected = {}

        def another_run(cfg, name, body, workspace, out, role, session, **kwargs):
            self.assertEqual(run.git(workspace, "rev-parse", "refs/remotes/origin/main"), base)
            self.git("branch", "ak/new-run")
            self.git("update-ref", "refs/remotes/origin/main", self.head)
            expected["refs"] = self.git("for-each-ref", "--format=%(refname) %(objectname)")
            return real_call(cfg, name, body, workspace, out, role, session, **kwargs)

        with patch.object(worker, "call", side_effect=another_run):
            self.assertEqual(self.review({
                "git": [["switch", "-q", "-c", "review-probe"],
                        ["branch", "-D", "ak/landed"]],
                "files": {"probe.txt": "reviewer commit\n"}, "commit": True, "push": True}), "PASS")
        self.assertEqual(self.git("for-each-ref", "--format=%(refname) %(objectname)"),
                         expected["refs"], "the reviewer's push changed shared refs")
        pushed = json.loads((self.lp.dir("reviewer") / "push.json").read_text())
        self.assertNotEqual(pushed["code"], 0, pushed["stderr"])
        self.assert_restored()
        self.assertIn("+reviewer commit", self.archive.read_text())

    def test_branch_switches_and_detached_head_do_not_reach_the_fixer(self):
        real_changes = run.reviewer_changes

        @contextmanager
        def check_reset(wt, out, log, **_kw):
            with real_changes(wt, out, log):
                yield
            self.assertEqual(run.git(wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
            self.assertEqual(run.git(wt, "rev-parse", "HEAD"), self.head)

        for row in (
                {"git": [["switch", "-q", "-c", "probe"]]},
                {"git": [["switch", "-q", "-c", "probe"]],
                 "files": {"probe.txt": "reviewer commit\n"}, "commit": True},
                {"git": [["checkout", "-q", "--detach", "HEAD~1"]]}):
            with self.subTest(row=row):
                try:
                    with patch.object(run, "reviewer_changes", side_effect=check_reset):
                        self.assertEqual(self.review(row), "PASS")
                    self.assert_restored()
                    self.assertIn("# checkout:", self.archive.read_text())
                    (self.wt / "fixer.txt").write_text("fixer work\n")
                    run.commit_leftovers(self.wt, self.logs.append, self.lp.artifacts)
                    self.assertNotEqual(self.git("rev-parse", "ak/fix-api"), self.head)
                    self.assertEqual(self.git("rev-parse", "ak/fix-api"),
                                     self.git("rev-parse", "HEAD"))
                finally:
                    self.git("symbolic-ref", "HEAD", "refs/heads/ak/fix-api")
                    self.git("reset", "--hard", self.head)
                    if self.git("branch", "--list", "probe"):
                        self.git("branch", "-D", "probe")

    def test_a_role_fixture_below_a_repository_is_not_a_review_checkout(self):
        def fake(cfg, name, body, workspace, out, role, session, **_kw):
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text("VERDICT: PASS")
            return 0, "VERDICT: PASS", None, False

        with patch.object(worker, "call", side_effect=fake):
            for role in ("reviewer", "reviewer-pr"):
                self.assertEqual(run.call_retrying(
                    self.lp.cfg, "astra", "Review.", self.root, self.lp.dir(role), role,
                    None, self.logs.append)[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
