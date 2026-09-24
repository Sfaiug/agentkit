"""Finding 11: automatic conservative retention and useful history, entirely offline.

All writable state, fake adapters and socket directories live inside this checkout. No
collector is ever pointed at the owner's ~/.agentkit, and no real model or account is used.
"""

from contextlib import ExitStack, redirect_stdout
import fcntl
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REAL_TMUX = shutil.which("tmux")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, retention, run, update, watch

DAY = 86400


class RetainState(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".retention-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        sockets, binaries, adapters = (self.root / name for name in ("sockets", "bin", "adapters"))
        for directory in (sockets, binaries, adapters):
            directory.mkdir(mode=0o700)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{binaries}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AK_RUN_LOG": "", "AGENTKIT_DISCORD_WEBHOOK": "off", "TMUX": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets),
            "AGENTKIT_GC_DISK_PERCENT": "100", "PYTHONDONTWRITEBYTECODE": "1",
            "RETENTION_FIXTURE": str(self.root), config.ADAPTER_DIR_ENV: str(adapters)}))
        self.script(binaries / "tmux", '''import os, sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
assert os.environ["TMUX_TMPDIR"].startswith(os.environ["RETENTION_FIXTURE"])
print("no server running on fixture socket")
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(binaries / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
        config.ensure_dirs()
        self.cfg = config.load()
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(n for n in workers if config.model(self.cfg, n)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        for harness in {m["harness"] for m in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", '''import json, pathlib, sys
if sys.argv[1] == "usage":
    print('{"meters":[{"name":"weekly","used":0}]}'); sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}'); sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
review = pathlib.Path(sys.argv[5]).read_text().startswith("You are the reviewer")
if not review:
    pathlib.Path(sys.argv[4], "deliverable.txt").write_text("unique fixture output")
(out / "final.md").write_text("VERDICT: PASS\\n## Findings\\n- none" if review else "## Summary\\nDelivered.")
(out / "session_id").write_text("fake-review" if review else "fake-execute")
''')
        self.now = time.time()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q", "-b", "main")
        self.git(self.repo, "config", "user.name", "fixture")
        self.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "tracked").write_text("committed result\n")
        (self.repo / ".gitignore").write_text("node_modules/\n.env\nexports/\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "fixture base")
        self.head = self.git(self.repo, "rev-parse", "HEAD")
        self.children = []
        # Only fixture-owned processes are visible to this offline test. Production's
        # unreadable-process refusal is tested separately; never inspect account processes.
        self.stack.enter_context(patch.object(retention, "process_dirs", side_effect=lambda:
            [Path(f"/proc/{os.getpid()}"), *[Path(f"/proc/{c.pid}") for c in self.children
                                          if c.poll() is None]]))
        self.addCleanup(self.stop_children)

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def git(self, repo, *args):
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def stop_children(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)

    def old(self, path, age=20 * DAY):
        # Walk links themselves, never their targets. Fake clock ages are the only aging used.
        if not path.is_symlink() and path.is_dir():
            for child in path.iterdir():
                self.old(child, age)
        os.utime(path, (self.now - age, self.now - age), follow_symlinks=False)

    def receipt(self, name, state="pass", age=20 * DAY, **extra):
        directory, wt = config.RUNS / name, config.WT / name
        directory.mkdir()
        self.git(self.repo, "worktree", "add", "-q", str(wt), "-b", "ak/" + name)
        record = {"run_id": name, "title": name, "state": state, "verdict": "PASS",
                  "repo": str(self.repo), "worktree": str(wt), "branch": "ak/" + name,
                  "base": "main", "delivery_sha": self.head, "merged": True,
                  "started_at": self.now - age - 300, "finished_at": self.now - age,
                  "pid": 99999999, "reported": True, "launched_session": None,
                  "executor": self.executor, "reviewer": self.reviewer, **extra}
        run.save_state(directory, record)
        (directory / "result.md").write_text("result and delivery location\n")
        (directory / "task.md").write_text("task\n")
        (directory / "log.txt").write_text("diagnostics\n" * 1000)
        (directory / "attachment.txt").write_text("user attachment survives\n")
        self.old(directory, age)
        return directory, wt

    def ephemeral(self, name, kind="smoke", age=20 * DAY, finished=True, **owner):
        path = config.TMP / name
        if kind == "smoke":
            path.mkdir()
            (path / "fixture.txt").write_text("disposable test files\n")
        else:
            path.write_text("temporary stream\n")
        retention.begin(path, kind)
        record = retention.read_json(retention.marker(path))
        record.update({"pid": 99999999, "process_identity": None, "created_at": self.now - age, **owner})
        if finished:
            record["finished_at"] = self.now - age
        retention.marker(path).write_text(json.dumps(record))
        self.old(path, age)
        self.old(retention.marker(path), age)
        return path

    def capture(self, command, args):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(command(args), 0)
        return output.getvalue()

    def snapshot(self, path, access_times=True):
        # Include inode, ownership, modes, contents and all filesystem timestamps. Reads in
        # this snapshot use the same no-atime primitive, so the assertion cannot hide writes.
        result = {}
        def visit(item):
            info = item.lstat()
            data = None if item.is_symlink() else (
                retention.read_bytes(item) if item.is_file() else None)
            result[str(item)] = (info.st_mode, info.st_uid, info.st_gid, info.st_ino,
                                 info.st_nlink, info.st_size, info.st_atime_ns if access_times else None,
                                 info.st_mtime_ns, info.st_ctime_ns, data)
            if not item.is_symlink() and item.is_dir():
                for child in retention.children(item):
                    visit(child)
        visit(path)
        return result

    def test_month_fixture_exact_plan_removal_identity_idempotency_and_history(self):
        merged, merged_wt = self.receipt("01-merged")
        (merged_wt / "node_modules").mkdir()
        (merged_wt / "node_modules" / "generated").write_text("reconstructible dependencies")
        failed, failed_wt = self.receipt("02-failed", state="fail", merged=False)
        interrupted, _ = self.receipt("03-interrupted", state="interrupted", merged=False,
                                      finished_at=None, interrupted_at=self.now - 20 * DAY)
        active, _ = self.receipt("04-active", state="running", merged=False,
                                 finished_at=None, **run.process_owner())
        recent, recent_wt = self.receipt("05-recent", age=60)
        unmerged, _ = self.receipt("06-unmerged", merged=False)
        scratch, scratch_wt = self.receipt("07-scratch", scratch=True, repo=None, merged=False)
        work = config.WORK / scratch.name
        work.mkdir()
        (work / "deliverable").write_text("cannot reconstruct this")
        record = run.read_state(scratch)
        record["worktree"] = str(work)
        run.save_state(scratch, record)
        old_smoke = self.ephemeral("smoke-old")
        old_view = self.ephemeral("view-old.txt", "viewer")
        old_update = self.ephemeral("update-old.log", "update")
        self.ephemeral("smoke-recent", age=60)
        # A dead interrupted writer is tmp like any other: a day, not a month.
        interrupted_tmp = self.ephemeral("smoke-interrupted", finished=False)
        abandoned = self.ephemeral("smoke-abandoned", age=31 * DAY, finished=False)
        live = self.ephemeral("view-live.txt", "viewer", **run.process_owner())
        foreign = config.TMP / "smoke-foreign"
        foreign.mkdir()
        (foreign / "keep").write_text("a name is not ownership")
        self.old(foreign)
        link = config.TMP / "smoke-link"
        link.symlink_to(foreign, target_is_directory=True)
        # A link *inside* an owned tree is removed as a link; its foreign target is untouched.
        (old_smoke / "external").symlink_to(foreign, target_is_directory=True)
        self.old(old_smoke)
        # Merged checkouts and their logs go on the first pass. A failed checkout older
        # than a week goes too. A delivered scratch workspace stays with its run directory.
        # Tmp older than a day goes.
        paths = {str(merged_wt), str(merged / "log.txt"), str(recent_wt), str(recent / "log.txt"),
                 str(failed_wt), str(old_smoke), str(old_view), str(old_update),
                 str(abandoned), str(interrupted_tmp)}
        before = self.snapshot(self.root)
        plan = run.gc_plan()
        self.assertEqual({p["path"] for p in plan}, paths)
        dry = self.capture(run.cmd_gc, ["--dry-run"])
        after_plan = self.snapshot(self.root)
        self.assertEqual([key for key in before if before[key] != after_plan.get(key)], [])
        self.assertEqual(after_plan, before)
        for path in paths:
            self.assertIn(path, dry)
        removed = run.gc(lambda _: None)
        self.assertEqual(set(removed), paths)
        self.assertFalse(merged_wt.exists())
        self.assertFalse(recent_wt.exists())
        self.assertFalse(failed_wt.exists())
        self.assertEqual((work / "deliverable").read_text(), "cannot reconstruct this")
        gone = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet",
                               "refs/heads/ak/01-merged"], capture_output=True, text=True)
        self.assertNotEqual(gone.returncode, 0, "the local branch survived the merged checkout")
        self.assertTrue((merged / "result.md").exists())
        self.assertEqual(gzip.decompress((merged / "log.txt.gz").read_bytes()), b"diagnostics\n" * 1000)
        self.assertEqual((merged / "attachment.txt").read_text(), "user attachment survives\n")
        # The git worktree the receipt first cut is no longer the run's checkout; the
        # scratch workspace it was pointed at goes only with its run directory.
        self.assertTrue(all(p.exists() for p in (scratch_wt, live, foreign)))
        self.assertTrue(link.is_symlink())
        after = self.snapshot(config.HOME)
        self.assertEqual(run.gc(lambda _: None), [])
        self.assertEqual(self.snapshot(config.HOME), after)
        rows = json.loads(self.capture(run.cmd_status, ["--json"]))
        self.assertEqual(rows[0]["run_id"], active.name)
        self.assertTrue({interrupted.name, unmerged.name}.issubset({s["run_id"] for s in rows}))
        self.assertNotIn(failed.name, {s["run_id"] for s in rows})
        self.assertNotIn(merged.name, {s["run_id"] for s in rows})
        history = json.loads(self.capture(run.cmd_status, ["--history", "--json"]))
        self.assertIn(failed.name, {s["run_id"] for s in history})
        old = next(s for s in history if s["run_id"] == merged.name)
        self.assertEqual({k: old[k] for k in run.read_state(merged)}, run.read_state(merged))
        self.assertEqual(old["paths"]["result"], str(merged / "result.md"))
        self.assertFalse(old["paths"]["workspace_present"])
        self.assertIn(str(merged / "result.md"), self.capture(run.cmd_status, [merged.name]))
        self.assertIn("--history", self.capture(run.cmd_status, []))
        # The compressed log still holds the diagnostics `ak run status` reads.
        self.assertEqual(gzip.decompress((merged / "log.txt.gz").read_bytes()), b"diagnostics\n" * 1000)

    def test_pressure_keeps_recent_failed_unmerged_and_unique_work(self):
        old, old_wt = self.receipt("two-days", age=2 * DAY)
        recent, recent_wt = self.receipt("today", age=60)
        failed, failed_wt = self.receipt("failed", state="fail", merged=False)
        unmerged, unmerged_wt = self.receipt("unmerged", merged=False)
        self.ephemeral("view-today.txt", "viewer", age=60)
        old_view = self.ephemeral("view-two-days.txt", "viewer", age=2 * DAY)
        dirty, dirty_wt = self.receipt("dirty")
        (dirty_wt / "tracked").write_text("unique uncommitted work")
        ignored, ignored_wt = self.receipt("ignored")
        (ignored_wt / ".env").write_text("unique ignored output")
        extra, extra_wt = self.receipt("extra-commit")
        (extra_wt / "unique").write_text("new commit after merge")
        self.git(extra_wt, "add", ".")
        self.git(extra_wt, "commit", "-qm", "unique work")
        foreign, _ = self.receipt("foreign-path")
        state = run.read_state(foreign)
        state["worktree"] = str(self.repo)
        run.save_state(foreign, state)
        # Merged checkouts go without waiting out the week, and tmp older than a day goes,
        # pressure or not. A failed checkout of twenty days goes; unique and unmerged work stays.
        expected = {str(old_wt), str(old / "log.txt"), str(recent_wt), str(recent / "log.txt"),
                    str(failed_wt), str(old_view)}
        self.assertEqual({item["path"] for item in run.gc_plan()}, expected)
        with patch.object(run, "disk_pressure", return_value=(99, 85)):
            self.assertEqual({item["path"] for item in run.gc_plan()}, expected)
            self.assertEqual(set(run.gc(lambda _: None)), expected)
            self.assertEqual(run.gc(lambda _: None), [])
        for directory in (unmerged, dirty, ignored, extra, foreign):
            self.assertTrue((directory / "log.txt").exists())
        self.assertTrue((failed / "log.txt").exists())
        self.assertFalse((recent / "log.txt").exists())
        for path in (unmerged_wt, dirty_wt, ignored_wt, extra_wt):
            self.assertTrue(path.exists())
        self.assertFalse(recent_wt.exists())
        self.assertFalse(failed_wt.exists())
        self.assertEqual((dirty_wt / "tracked").read_text(), "unique uncommitted work")

    def test_active_handles_leases_symlinks_and_interrupted_writes(self):
        view = self.ephemeral("view-held.txt", "viewer")
        ready = self.root / "ready"
        child = subprocess.Popen([sys.executable, "-c", "import pathlib,sys,time; "
                                  "f=open(sys.argv[1]); pathlib.Path(sys.argv[2]).touch(); time.sleep(60)",
                                  str(view), str(ready)])
        self.children.append(child)
        deadline = time.monotonic() + 10
        while not ready.exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        held = self.ephemeral("smoke-lease")
        partial = self.ephemeral("smoke-partial")
        receipt = retention.marker(partial)
        receipt.with_name(receipt.name + ".part").write_text('{"unfinished":')
        symlinked = self.ephemeral("view-link.txt", "viewer")
        symlinked.unlink()
        symlinked.symlink_to(view)
        corrupt = self.ephemeral("smoke-corrupt")
        retention.marker(corrupt).write_text("{")
        with retention.marker(held).open() as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            self.assertEqual(run.gc_plan(), [])
            self.assertEqual(run.gc(lambda _: None), [])
        child.terminate()
        child.wait(timeout=10)
        candidates = {item["path"] for item in run.gc_plan()}
        self.assertEqual(candidates, {str(view), str(held)})
        # A file changed since planning cannot be removed by a cached candidate.
        item = next(i for i in run.gc_plan() if i["path"] == str(view))
        view.write_text("a writer returned")
        self.assertFalse(retention.remove_ephemeral(item))
        self.assertTrue(view.exists())

    def test_planning_does_not_dereference_worktree_archive_or_partial_symlinks(self):
        directory, wt = self.receipt("symlink-checkout")
        self.git(self.repo, "worktree", "remove", str(wt))
        wt.symlink_to(self.repo, target_is_directory=True)
        logs, _ = self.receipt("symlink-archive")
        (logs / "log.txt.gz").symlink_to(directory / "log.txt")
        ephemeral = self.ephemeral("smoke-part-link")
        marker = retention.marker(ephemeral)
        marker.with_name(marker.name + ".part").symlink_to(directory / "run.json")
        before = self.snapshot(self.root)
        plan = run.gc_plan()
        after = self.snapshot(self.root)
        self.assertEqual([key for key in before if before[key] != after.get(key)], [])
        self.assertEqual(after, before)
        self.assertEqual({item["path"] for item in plan}, {str(config.WT / logs.name)})
        # Foreign hard-linked data cannot acquire ownership by being put in a temporary tree.
        hard = self.ephemeral("smoke-hardlink")
        os.link(directory / "attachment.txt", hard / "foreign-data")
        self.old(hard)
        self.assertNotIn(str(hard), {item["path"] for item in run.gc_plan()})

    def test_malformed_receipts_do_not_authorize_retention(self):
        nan, nan_wt = self.receipt("nan", finished_at=float("nan"))
        for name, fields in (("bad-pid", {"pid": "not-a-pid"}),
                             ("bad-identity", {"process_identity": ["unreadable"]}),
                             ("bad-worktree", {"worktree": ["foreign"]})):
            self.receipt(name, **fields)
        artifact = self.ephemeral("smoke-bad-clock")
        path = retention.marker(artifact)
        record = retention.read_json(path)
        record["finished_at"] = float("nan")
        path.write_text(json.dumps(record))
        self.old(path)
        bad_kind = self.ephemeral("smoke-bad-kind")
        kind_path = retention.marker(bad_kind)
        record = retention.read_json(kind_path)
        record["kind"] = ["smoke"]
        kind_path.write_text(json.dumps(record))
        self.old(kind_path)
        # A NaN clock does not keep a merged checkout whose loop is gone. A pid or
        # identity that cannot be read, or a worktree that is not the run's, still
        # authorises nothing, and neither does a tmp receipt with a NaN clock.
        expected = {str(nan_wt), str(nan / "log.txt")}
        self.assertEqual({item["path"] for item in run.gc_plan()}, expected)
        self.assertEqual(set(run.gc(lambda _: None)), expected)
        self.assertFalse(nan_wt.exists())
        for name in ("bad-pid", "bad-identity", "bad-worktree"):
            self.assertTrue((config.WT / name).exists(), name)
        self.assertTrue((config.TMP / "smoke-bad-clock").exists())
        self.assertTrue((config.TMP / "smoke-bad-kind").exists())

    def test_fake_run_deliverables_and_viewer_receipts_are_kept(self):
        task = self.root / "task.md"
        task.write_text("---\nrepo: none\nrounds: 1\n---\n# Fixture\n\n## Done when\n```bash\ntest -f deliverable.txt\n```\n")
        self.capture(run.main, [str(task), "--exec", self.executor, "--review", self.reviewer])
        directory = run.run_dirs()[0]
        state = run.read_state(directory)
        self.assertEqual(state["state"], "pass")
        work = Path(state["worktree"])
        # `ak run status` names the result; the menu no longer follows runs.
        self.assertIn(str(directory / "result.md"), self.capture(run.cmd_status, [directory.name]))
        # The scratch workspace is the delivery and outlives the run. A recent finished_at
        # keeps the run directory and it; ageing the directory's mtime is not the clock
        # that collects them. The run's own clock is, and they go together once its
        # writer -- this process, which ran it in-process -- is gone.
        self.assertEqual((work / "deliverable.txt").read_text(), "unique fixture output")
        self.assertIn("deliverable.txt", (directory / "result.md").read_text())
        self.old(directory, 31 * DAY)
        with patch.object(run, "disk_pressure", return_value=(99, 85)):
            run.gc(lambda _: None)
        self.assertTrue((directory / "result.md").exists())
        self.assertTrue((work / "deliverable.txt").exists())
        state = run.read_state(directory)
        state.update(started_at=self.now - 31 * DAY, finished_at=self.now - 31 * DAY,
                     pid=99999999, process_identity=None)
        run.save_state(directory, state)
        run.gc(lambda _: None)
        self.assertFalse(directory.exists())
        self.assertFalse(work.exists())

    def test_real_smoke_layout_collects_stale_sockets_but_preserves_live_ones(self):
        smoke = self.ephemeral("smoke-with-sockets")
        def bind(directory, name="agentkit-test"):
            directory.mkdir(parents=True, exist_ok=True)
            sock = socket.socket(socket.AF_UNIX)
            previous = Path.cwd()
            try:
                os.chdir(directory)     # private relative path avoids UNIX's pathname limit
                sock.bind(name)
                sock.listen()
            finally:
                os.chdir(previous)
            return sock
        for directory in ("tmux", "ovt", "seen-tmux", "stall-tmux", "runs-tmux"):
            bind(smoke / directory / f"tmux-{os.getuid()}").close()
        self.old(smoke)
        active = self.ephemeral("smoke-live-socket")
        live = bind(active / "tmux", "live-viewer")
        self.addCleanup(live.close)
        self.old(active)
        before = self.snapshot(config.HOME)
        with patch.object(retention, "unix_sockets", return_value=None):
            self.assertEqual(run.gc_plan(), [])
        plan = run.gc_plan()
        self.assertEqual({item["path"] for item in plan}, {str(smoke)})
        self.capture(run.cmd_gc, ["--dry-run"])
        self.assertEqual(self.snapshot(config.HOME), before)
        self.assertEqual(run.gc(lambda _: None), [str(smoke)])
        self.assertTrue(active.exists())
        self.assertEqual(run.gc(lambda _: None), [])
        live.close()
        self.assertEqual(run.gc(lambda _: None), [str(active)])
        self.assertEqual(run.gc(lambda _: None), [])

    def test_same_second_updates_use_unique_logs_and_optional_registration(self):
        self.muse_install_layout()
        with patch.object(update, "fresh_unavailable", return_value=""), \
                patch.object(update, "version", return_value="1.0.0"), \
                patch.object(update, "step", return_value=True), \
                patch.object(update, "fresh_gate", return_value=(True, "fixture passed")), \
                patch.object(update, "datetime") as clock, redirect_stdout(io.StringIO()):
            clock.now.return_value = __import__("datetime").datetime(2026, 9, 11, 12, 0, 0)
            for _ in range(2):
                self.assertEqual(update.main([]), 0)
        logs = list(config.TMP.glob("update-*.log"))
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(retention.read_json(retention.marker(log))["finished_at"] for log in logs))
        alias = self.root / "symlinked-home"
        alias.symlink_to(config.HOME, target_is_directory=True)
        with patch.object(config, "TMP", alias / "tmp"):
            directory, wt = self.receipt("view-without-registration", age=60)
            with redirect_stdout(io.StringIO()):
                run.cmd_status([directory.name])
            self.assertEqual(list(config.TMP.glob("view-*.txt")), [])
            with patch.object(update, "fresh_unavailable", return_value=""), \
                    patch.object(update, "version", return_value="1.0.0"), \
                    patch.object(update, "step", return_value=True), \
                    patch.object(update, "fresh_gate", return_value=(True, "fixture passed")), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(update.main([]), 0)
            self.assertEqual(len(list(config.TMP.glob("update-*.log"))), 3)
            # The minute-old merged checkout is eligible at once. The symlinked tmp
            # still contributes nothing: a link is not a receipt.
            self.assertEqual({item["path"] for item in run.gc_plan()},
                             {str(wt), str(directory / "log.txt")})
        # The actual shell prologue also succeeds when HOME contains a symlink; it simply
        # leaves its files unregistered. No models, sockets or account commands follow it.
        home = self.root / "linked-home"
        home.symlink_to(self.root, target_is_directory=True)
        source = (REPO / "tests/smoke.sh").read_text()
        block = source[source.index('WORK="$HOME/.agentkit/tmp/smoke-'):source.index("# --- the suite's own tmux")]
        child = subprocess.run(["bash", "-c", block], cwd=self.root, capture_output=True, text=True,
                               env={**os.environ, "HOME": str(home), "REPO": str(REPO)})
        self.assertEqual(child.returncode, 0, child.stderr)
        smoke = next(config.TMP.glob("smoke-*"))
        self.assertFalse(retention.marker(smoke).exists())

    def test_archive_crash_recovery_and_unknown_files_are_lossless(self):
        directory, wt = self.receipt("archive")
        log = directory / "log.txt"
        data = log.read_bytes()
        part = directory / "log.txt.gz.part"
        part.write_bytes(b"interrupted compressor")
        custom = directory / "attachments"
        custom.mkdir()
        (custom / "events.jsonl").write_text("user output, not a worker stream")
        self.old(custom)
        expected = {str(wt), str(log)}
        self.assertEqual({item["path"] for item in run.gc_plan()}, expected)
        self.assertEqual(set(run.gc(lambda _: None)), expected)
        self.assertEqual(gzip.decompress((directory / "log.txt.gz").read_bytes()), data)
        self.assertFalse(part.exists())
        self.assertTrue((custom / "events.jsonl").exists())
        # Publication succeeded but the process died before unlinking the source.
        log.write_bytes(data)
        self.old(log)
        self.assertEqual(run.gc(lambda _: None), [str(log)])
        self.assertEqual(gzip.decompress((directory / "log.txt.gz").read_bytes()), data)
        log.write_bytes(b"different unique content")
        self.old(log)
        self.assertEqual(run.gc(lambda _: None), [])
        self.assertEqual(log.read_bytes(), b"different unique content")

    def test_unknown_processes_live_worktrees_and_partial_state_prevent_collection(self):
        directory, wt = self.receipt("busy-checkout")
        temp = self.ephemeral("smoke-unknown")
        with patch.object(retention, "process_paths", return_value=None):
            self.assertEqual(run.gc_plan(), [])
        with patch.object(retention, "process_paths", return_value={str(wt / "tracked")}):
            self.assertEqual({item["path"] for item in run.gc_plan()}, {str(temp)})
        (directory / "run.tmp").write_text('{"state":"running"')
        self.assertEqual({item["path"] for item in run.gc_plan()}, {str(temp)})
        self.assertTrue(wt.exists())
        self.assertTrue((directory / "log.txt").exists())

    def test_empty_state_and_symlinked_roots_have_read_only_empty_plans(self):
        empty = self.root / "absent"
        with patch.object(config, "HOME", empty), patch.object(config, "RUNS", empty / "runs"), \
                patch.object(config, "TMP", empty / "tmp"):
            self.assertIn("no eligible", self.capture(run.cmd_gc, ["--dry-run"]))
            self.assertFalse(empty.exists())
        target = self.ephemeral("smoke-foreign-target")
        alias = self.root / "alias"
        alias.symlink_to(config.TMP, target_is_directory=True)
        with patch.object(config, "TMP", alias):
            self.assertEqual(run.gc_plan(), [])
        self.assertTrue(target.exists())

    @unittest.skipUnless(REAL_TMUX, "tmux not installed")
    def test_real_tmux_retires_only_the_dead_marked_detached_seat(self):
        # The checkout path exceeds UNIX socket's limit even before a fixture suffix. Keep
        # the same literal test socket name, addressed relative to its private directory.
        sockets = self.root / "sockets"
        env = {**os.environ, "TMUX_TMPDIR": str(sockets)}
        def tmux(*args, **kwargs):
            self.assertFalse(kwargs.get("socket"))
            proc = subprocess.run([REAL_TMUX, "-L", "agentkit-test", "-S", "./agentkit-test", *args],
                                  capture_output=True, text=True, env=env, cwd=sockets)
            return proc.returncode, (proc.stdout + proc.stderr).strip()
        self.addCleanup(lambda: tmux("kill-server"))
        started = tmux("new-session", "-d", "-s", "dead", "sleep 60")
        self.assertEqual(started[0], 0, started)
        option = tmux("set-option", "-t", "=dead:", "remain-on-exit", "on")
        self.assertEqual(option[0], 0, option)
        marked = tmux("set-option", "-t", "=dead:", orch.MARK, "1")
        self.assertEqual(marked[0], 0, marked)
        self.assertEqual(tmux("respawn-pane", "-k", "-t", "=dead:", "true")[0], 0)
        self.assertEqual(tmux("new-session", "-d", "-s", "live", "sleep 60")[0], 0)
        self.assertEqual(tmux("set-option", "-t", "=live:", orch.MARK, "1")[0], 0)
        deadline = time.monotonic() + 10
        while tmux("display-message", "-p", "-t", "=dead:", "#{pane_dead}")[1] != "1":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        with patch.object(orch, "tmux_out", side_effect=tmux):
            self.assertFalse(orch.retire_exited("dead"))  # freshly exited, even with an old record
            # An actual attached terminal must also veto the final tmux conditional.
            import pty
            master, slave = pty.openpty()
            self.addCleanup(os.close, master)
            self.addCleanup(os.close, slave)
            client = subprocess.Popen([REAL_TMUX, "-L", "agentkit-test", "-S", "./agentkit-test",
                                       "attach-session", "-t", "=dead"], cwd=sockets,
                                      env={**env, "TERM": "xterm"}, stdin=slave, stdout=slave, stderr=slave)
            self.children.append(client)
            deadline = time.monotonic() + 10
            while tmux("display-message", "-p", "-t", "=dead:", "#{session_attached}")[1] != "1":
                self.assertLess(time.monotonic(), deadline)
                self.assertIsNone(client.poll())
                time.sleep(.01)
            with patch.object(orch.time, "time", return_value=self.now + 8 * DAY):
                self.assertFalse(orch.retire_exited("dead"))
                self.assertEqual(tmux("detach-client", "-s", "=dead")[0], 0)
                client.wait(timeout=5)
                self.assertFalse(orch.retire_exited("live"))
                self.assertTrue(orch.retire_exited("dead"))
        self.assertEqual(tmux("has-session", "-t", "=live")[0], 0)
        self.assertEqual(tmux("has-session", "-t", "=dead")[0], 1)

    def test_smoke_and_update_producers_register_their_own_files_offline(self):
        self.muse_install_layout()
        source = (REPO / "tests/smoke.sh").read_text()
        block = source[source.index('WORK="$HOME/.agentkit/tmp/smoke-'):source.index("# --- the suite's own tmux")]
        # A passed suite takes its sandbox with it; a failed one keeps it, receipt signed off.
        child = subprocess.run(["bash", "-c", block], env={**os.environ, "REPO": str(REPO)},
                               cwd=self.root, capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(list(config.TMP.glob("smoke-*")), [])
        child = subprocess.run(["bash", "-c", block + "\nexit 1\n"],
                               env={**os.environ, "REPO": str(REPO)},
                               cwd=self.root, capture_output=True, text=True)
        self.assertEqual(child.returncode, 1, child.stderr)
        smoke = next(config.TMP.glob("smoke-*"))
        record = retention.read_json(retention.marker(smoke))
        self.assertEqual(record["kind"], "smoke")
        self.assertGreater(record["finished_at"], 0)
        self.assertFalse(retention.writer_active(record))
        # Version/upgrade/gate operations are stand-ins. The real update owns its log receipt.
        with patch.object(update, "fresh_unavailable", return_value=""), \
                patch.object(update, "version", return_value="1.0.0"), \
                patch.object(update, "step", return_value=True), \
                patch.object(update, "fresh_gate", return_value=(True, "fixture passed")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(update.main([]), 0)
        log = next(config.TMP.glob("update-*.log"))
        receipt = retention.read_json(retention.marker(log))
        self.assertEqual(receipt["kind"], "update")
        self.assertGreater(receipt["finished_at"], 0)

    def muse_install_layout(self):
        # The commands remain stand-ins, but update's real snapshot preflight needs a
        # complete install. Keep it beside the existing forbidden-call launcher in bin/.
        binaries = self.root / "bin"
        (binaries / ".muse-version").write_text("1.0.0-R1\n")
        (binaries / ".muse-release-info.json").write_text('{"version":"1.0.0-R1"}\n')
        self.script(binaries / "muse-bin-1.0.0-R1", 'raise AssertionError("external call forbidden")\n')

    def seat(self, name, **extra):
        config.save_session(self.cfg, name, self.cfg["defaults"]["orchestrator"],
                            self.cfg["defaults"]["workers"],
                            {"cwd": str(self.root), "created": self.now - 30 * DAY,
                             "seen": self.now - 20 * DAY, **extra})

    def test_automatic_watch_tick_retention_even_when_github_is_unavailable(self):
        old, wt = self.receipt("auto-old")
        disposable = self.ephemeral("smoke-auto")
        self.seat("gone")
        with patch.object(watch, "health"), patch.object(notify, "retry_pending"), \
                patch.object(run, "schedule_gc", side_effect=lambda log: run.gc(log, automatic=True)), \
                patch.object(watch, "gh_json", return_value=(None, "offline")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main([]), 0)     # the offline GitHub is skipped, not fatal
        self.assertFalse(wt.exists())
        self.assertFalse(disposable.exists())
        self.assertTrue((old / "result.md").exists())
        self.assertFalse(config.session_path("gone").exists())
        untouched = self.ephemeral("smoke-dry-tick")
        with patch.object(watch, "health"), patch.object(notify, "retry_pending"), \
                patch.object(watch, "gh_json", return_value=(None, "offline")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main(["--dry-run"]), 0)
        self.assertTrue(untouched.exists())

    def test_seat_retention_uses_exit_clock_and_protects_live_attached_and_jobs(self):
        seats = []
        for name, exited, attached, age in (("dead-old", True, False, 20 * DAY),
                                           ("dead-recent", True, False, 60),
                                           ("attached", True, True, 20 * DAY),
                                           ("live", False, False, 20 * DAY),
                                           ("legacy", True, False, 20 * DAY),
                                           ("failed-job", True, False, 20 * DAY),
                                           ("newly-dead", True, False, 0)):
            self.seat(name, exited_since=self.now - age if age else None)
            seats.append({"name": name, "exited": exited, "attached": attached,
                          "legacy": name == "legacy"})
        self.receipt("failed-job", state="fail", merged=False, launched_session="failed-job",
                     recovery_pending=True)
        retired = []
        with patch.object(orch, "sessions", return_value=seats), \
                patch.object(orch, "retire_exited", side_effect=lambda n: retired.append(n) or True), \
                patch.object(orch.time, "time", return_value=self.now):
            orch.stamp()
            first = json.loads(config.session_path("newly-dead").read_text())["exited_since"]
            orch.sweep(lambda _: None)
            self.assertEqual(retired, ["dead-old"])
            self.assertFalse(config.session_path("dead-old").exists())
            for name in ("dead-recent", "attached", "live", "legacy", "failed-job", "newly-dead"):
                self.assertTrue(config.session_path(name).exists())
            self.assertNotIn("exited_since", json.loads(config.session_path("attached").read_text()))
            self.assertNotIn("exited_since", json.loads(config.session_path("live").read_text()))
            orch.stamp()
            self.assertEqual(json.loads(config.session_path("newly-dead").read_text())["exited_since"], first)

    def test_failed_tmux_probe_does_not_forget_a_potentially_live_seat(self):
        self.seat("unknown")
        with patch.object(orch, "tmux_out", return_value=(1, "Permission denied")):
            orch.sweep(lambda _: None)
        self.assertTrue(config.session_path("unknown").exists())

    def test_completed_runs_do_not_pin_seats_or_default_status_forever(self):
        cases = {"failure": {"state": "fail"}, "error": {"state": "error"},
                 "review": {"review_pr": 1}, "no-merge": {"no_merge": True},
                 "review-posted": {"review_posted": True},
                 "recovery": {"state": "interrupted", "recovery_notified": True},
                 "active": {"state": "running", "finished_at": None, **run.process_owner()},
                 "pending-delivery": {}, "recent-failure": {"state": "fail", "age": 60}}
        for name, extra in cases.items():
            self.seat(name)
            self.receipt(name, age=extra.pop("age", 60 * DAY), merged=False,
                         launched_session=name, **extra)
        # Ordinary seat maintenance may read state on platforms without O_NOATIME.
        evidence = self.snapshot(config.RUNS, False), self.snapshot(config.WT, False)
        orch.sweep(lambda _: None)
        for name in cases:
            self.assertEqual(config.session_path(name).exists(), name in ("recovery", "active"), name)
        self.assertEqual((self.snapshot(config.RUNS, False), self.snapshot(config.WT, False)), evidence)
        rows = json.loads(self.capture(run.cmd_status, ["--json"]))
        self.assertEqual(rows[0]["run_id"], "active")
        self.assertEqual({s["run_id"] for s in rows},
                         {"active", "recovery", "pending-delivery", "recent-failure"})
        history = json.loads(self.capture(run.cmd_status, ["--history", "--json"]))
        self.assertEqual({s["run_id"] for s in history}, set(cases))
        for row in history:
            self.assertTrue(Path(row["paths"]["result"]).is_file())
            self.assertTrue(Path(row["paths"]["workspace"]).is_dir())
        self.assertIn("failure", self.capture(run.cmd_status, ["failure"]))

    def test_unread_questions_keep_dead_and_gone_seats_until_opened(self):
        for name in ("gone-question", "dead-question"):
            self.seat(name, exited_since=self.now - 20 * DAY)
            notify.record(name, "needs", "An unanswered fixture question")
            self.old(config.notify_path(name))
        dead = {"name": "dead-question", "exited": True, "attached": False}
        with patch.object(orch, "sessions", return_value=[dead]), \
                patch.object(orch, "retire_exited", return_value=True) as retire:
            for clock in (self.now, self.now + 60 * DAY):
                with patch.object(orch.time, "time", return_value=clock):
                    orch.sweep(lambda _: None)
                for name in ("gone-question", "dead-question"):
                    self.assertTrue(config.session_path(name).exists())
                    self.assertEqual(notify.last(name)["kind"], "needs")
                self.assertEqual({row["name"] for row in orch.listing()},
                                 {"gone-question", "dead-question"})
            retire.assert_not_called()
            for name in ("gone-question", "dead-question"):
                notice = retention.read_json(config.notify_path(name))
                notice["seen"] = self.now
                config.notify_path(name).write_text(json.dumps(notice))
            orch.sweep(lambda _: None)
            retire.assert_called_once_with("dead-question")
        self.assertFalse(config.session_path("gone-question").exists())
        self.assertFalse(config.session_path("dead-question").exists())

    def test_automatic_collection_is_detached_daily_and_skips_unknown_output_early(self):
        _, wt = self.receipt("build-output")
        dependencies = wt / "node_modules"
        dependencies.mkdir()
        for i in range(200):
            (dependencies / str(i)).write_text("reconstructible")
        output = wt / "zzz-deliverable"
        output.write_text("unique build output")
        # Unknown output after node_modules in traversal order still avoids dependency
        # traversal and tracked-blob hashing. These are cost assertions, not timing guesses.
        original_reading, original_hash = retention.reading, retention.git_hash
        def reading(path, **kwargs):
            self.assertFalse(path == dependencies or dependencies in path.parents)
            return original_reading(path, **kwargs)
        def hashing(kind, data):
            self.assertNotEqual(kind, b"blob")
            return original_hash(kind, data)
        with patch.object(retention, "reading", side_effect=reading), \
                patch.object(retention, "git_hash", side_effect=hashing):
            self.assertEqual(run.gc_plan(), [])
        with patch.object(run.subprocess, "Popen") as launch, \
                patch.object(run, "gc_candidates", side_effect=AssertionError("scanned in foreground")):
            run.schedule_gc(lambda _: None)
            launch.assert_called_once()
            self.assertEqual(launch.call_args.args[0][-2:], ["agentkit.retention", "collect"])
            self.assertTrue(launch.call_args.kwargs["start_new_session"])
            self.assertEqual(launch.call_args.kwargs["env"]["HOME"], str(self.root))
        candidate = self.ephemeral("smoke-daily")
        with patch.object(run.time, "time", return_value=self.now):
            self.assertEqual(run.gc(lambda _: None, automatic=True), [str(candidate)])
            before = self.snapshot(config.HOME)
            with patch.object(run, "gc_candidates", side_effect=AssertionError("daily cooldown")), \
                    patch.object(run.subprocess, "Popen", side_effect=AssertionError("daily cooldown")):
                self.assertEqual(run.gc(lambda _: None, automatic=True), [])
                run.schedule_gc(lambda _: None)
            self.assertEqual(self.snapshot(config.HOME), before)
        later = self.ephemeral("smoke-next-day")
        with patch.object(run.time, "time", return_value=self.now + DAY + 1):
            self.assertEqual(run.gc(lambda _: None, automatic=True), [str(later)])
        self.assertEqual(output.read_text(), "unique build output")

    def test_portable_seat_reads_keep_recovery_and_retire_read_notices(self):
        non_codex = next(n for n in config.offered(self.cfg)
                         if config.model(self.cfg, n)["harness"] != "codex")
        for mode in ("no-noatime", "linked-home"):
            with self.subTest(mode=mode), ExitStack() as stack:
                names = {key: mode + "-" + key for key in
                         ("done", "seen", "question", "dead", "running", "queued", "recovery")}
                for key, name in names.items():
                    self.seat(name, exited_since=self.now - 20 * DAY)
                    config.update_session(name, orchestrator=non_codex)
                for key in ("done", "seen", "question"):
                    notify.record(names[key], "done" if key == "done" else "needs", "fixture",
                                  seen=None if key == "question" else self.now)
                for key in ("running", "queued", "recovery"):
                    self.receipt(names[key], state="interrupted" if key == "recovery" else key,
                                 merged=False, launched_session=names[key])
                evidence = self.snapshot(config.RUNS, False), self.snapshot(config.WT, False)
                if mode == "no-noatime":
                    stack.enter_context(patch.object(os, "O_NOATIME", create=True))
                    del os.O_NOATIME
                else:
                    alias = self.root / "home-alias"
                    alias.symlink_to(config.HOME, target_is_directory=True)
                    stack.enter_context(patch.object(config, "HOME", alias))
                    for key in ("RUNS", "WT", "STATE", "TMP", "WORK", "ENV", "SECRETS"):
                        stack.enter_context(patch.object(config, key, alias / key.lower()))
                seats = [{"name": names[key], "exited": True, "attached": False}
                         for key in ("dead", "running", "queued", "recovery")]
                stack.enter_context(patch.object(orch, "sessions", return_value=seats))
                retire = stack.enter_context(patch.object(orch, "retire_exited", return_value=True))
                self.assertFalse(orch.unread_question(names["done"]))
                self.assertFalse(orch.unread_question(names["seen"]))
                self.assertTrue(orch.unread_question(names["question"]))
                listed = {row["name"] for row in orch.listing()}
                self.assertNotIn(names["done"], listed)
                self.assertNotIn(names["seen"], listed)
                self.assertIn(names["question"], listed)
                orch.sweep(lambda _: None)
                retire.assert_called_once_with(names["dead"])
                for key, name in names.items():
                    self.assertEqual(config.session_path(name).exists(),
                                     key in ("question", "running", "queued", "recovery"), key)
                # The strict planner and scheduler must still decline unsupported collection.
                with patch.object(run.subprocess, "Popen", side_effect=AssertionError("unsupported GC")):
                    for _ in range(3):
                        run.schedule_gc(lambda _: None)
                    self.assertEqual(run.gc_plan(), [])
            self.assertEqual((self.snapshot(config.RUNS, False), self.snapshot(config.WT, False)), evidence)

    def test_registration_process_failure_does_not_abort_smoke_or_update_jobs(self):
        source = (REPO / "tests/smoke.sh").read_text()
        block = source[source.index('WORK="$HOME/.agentkit/tmp/smoke-'):source.index("# --- the suite's own tmux")]
        for status in (0, 7):
            home = self.root / f"smoke-home-{status}"
            home.mkdir()
            child = subprocess.run(["bash", "-c", '''set -e
python3() { printf '%s\\n' "$*" >>"$HOME/registration-calls"; return 23; }
''' + block + f'\nprintf continued >"$HOME/continued"\nexit {status}\n'],
                env={**os.environ, "HOME": str(home), "REPO": str(REPO)},
                cwd=self.root, capture_output=True, text=True)
            self.assertEqual(child.returncode, status, child.stderr)
            self.assertTrue((home / "continued").exists())
            calls = (home / "registration-calls").read_text()
            self.assertIn(" begin ", calls)
            self.assertIn(f" settle {home}/.agentkit/tmp/smoke-", calls)
            self.assertIn(f" {status}\n", calls)
        python = self.root / "fake-python"
        self.script(python, '''import os, pathlib, sys
if sys.argv[1:3] == ["-m", "agentkit.retention"]:
    with pathlib.Path(os.environ["HOME"], "registration-calls").open("a") as out:
        out.write(sys.argv[3] + "\\n")
    raise RuntimeError("fixture registration process failure")
assert sys.argv[-1] == "update", sys.argv
print("fixture update ran")
sys.exit(int(os.environ["FIXTURE_UPDATE_RC"]))
''')
        for status in (0, 1):
            with patch.object(orch.sys, "executable", str(python)), \
                    patch.object(orch, "job_running", return_value=False), \
                    patch.object(orch, "tmux_out", return_value=(0, "")) as tmux:
                orch.start_update()
                script = tmux.call_args.args[-1]
            child = subprocess.run(["sh", "-c", script], cwd=self.root, capture_output=True, text=True,
                                   env={**os.environ, "FIXTURE_UPDATE_RC": str(status)})
            self.assertEqual(child.returncode, 0, child.stderr)
            result = (config.STATE / orch.UPDATE_RESULT).read_text()
            self.assertIn("FAILED" if status else "done", result)
            log = Path(result.split("(", 1)[1].split(")")[0])
            self.assertEqual(log.read_text(), "fixture update ran\n")
        self.assertEqual((self.root / "registration-calls").read_text().splitlines(),
                         ["begin", "finish", "begin", "finish"])

    def test_automatic_collection_records_actions_in_bounded_logs(self):
        directory, wt = self.receipt("logged-collection")
        temp = self.ephemeral("smoke-logged")
        path, previous = config.STATE / "gc.log", config.STATE / "gc.log.1"
        with patch.object(run.time, "time", return_value=self.now):
            expected = {str(wt), str(directory / "log.txt"), str(temp)}
            self.assertEqual(set(run.gc(lambda _: None, automatic=True)), expected)
        log = path.read_text()
        for action in (f"remove merged-worktree {wt}", f"compress merged-log {directory / 'log.txt'}",
                       f"remove smoke {temp}"):
            self.assertIn(action, log)
        first_log = log
        with patch.object(run, "GC_LOG_LIMIT", len(log.encode()) + 1):
            for days in (1, 2):
                with patch.object(run.time, "time", return_value=self.now + days * DAY + 1):
                    run.gc(lambda _: None, automatic=True)
        self.assertEqual(previous.read_text(), first_log)
        self.assertLessEqual(path.stat().st_size, len(first_log.encode()) + 1)
        self.assertEqual(sorted(p.name for p in config.STATE.glob("gc.log*")), ["gc.log", "gc.log.1"])
        before = self.snapshot(config.HOME)
        self.capture(run.cmd_gc, ["--dry-run"])
        self.assertEqual(self.snapshot(config.HOME), before)

    def test_collector_probe_and_log_paths_decline_unsafe_state(self):
        for path in (config.STATE / "gc.log", config.STATE / "gc.log.1"):
            candidate = self.ephemeral("smoke-protected-" + path.name)
            target = self.root / (path.name + "-foreign")
            target.write_text("keep")
            path.symlink_to(target)
            before = self.snapshot(config.HOME)
            self.assertEqual(run.gc(lambda _: None, automatic=True), [])
            self.assertTrue(candidate.exists())
            self.assertEqual(target.read_text(), "keep")
            self.assertEqual(self.snapshot(config.HOME), before)
            path.unlink()
        with patch.object(retention, "reading", side_effect=OSError("no-atime open denied")), \
                patch.object(run.subprocess, "Popen", side_effect=AssertionError("unsupported GC")):
            run.schedule_gc(lambda _: None)

    def test_malformed_runs_do_not_block_health_retry_menu_or_other_seats(self):
        for name, state in {"00-array": [], "01-scalar": 1,
                            "02-owner": {"state": "interrupted", "launched_session": ["bad"]},
                            "03-invalid-name": {"state": "interrupted", "launched_session": "bad/name"},
                            "04-pending": {"state": "fail", "pending_inbox": [1]}}.items():
            directory = config.RUNS / name
            directory.mkdir()
            (directory / "run.json").write_text(json.dumps(state))
        self.seat("gone")
        orch.sweep(lambda _: None)
        self.assertFalse(config.session_path("gone").exists())
        order = []
        with patch.object(notify, "retry_pending", side_effect=lambda **kw: order.append("retry")), \
                patch.object(watch, "health", side_effect=lambda *a: order.append("health")), \
                patch.object(run, "schedule_gc", side_effect=lambda *a: order.append("schedule")), \
                patch.object(orch, "sweep", side_effect=AttributeError("bad metadata")), \
                patch.object(watch, "gh_json", side_effect=lambda *a: (order.append("github") or
                                                                        (None, "offline"))), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main([]), 0)
        self.assertEqual(order, ["retry", "health", "schedule", "github"])
        good, _ = self.receipt("99-good", state="fail", reported=False, launched_session="open")
        bad, _ = self.receipt("98-bad", state="fail", reported=False, launched_session="bad/name")
        with patch.object(run, "schedule_gc"), \
                patch.object(orch, "sessions", return_value=[{"name": "open"}]), \
                patch.object(orch, "stamp"), patch.object(orch, "sweep", side_effect=ValueError("bad state")):
            messages = []
            orch.maintenance(messages.append)
        # v5m: maintenance reports no endings, so neither receipt is marked told; the
        # malformed one still cannot stop it, and the broken sweep is still warned about
        self.assertFalse(run.read_state(good)["reported"])
        self.assertFalse(run.read_state(bad)["reported"])
        self.assertTrue(any("WARN" in line for line in messages))

    def test_seat_kill_rechecks_tmux_conditions_and_changed_panes(self):
        calls = []
        def tmux(*args, **kwargs):
            calls.append(args)
            if args[0] == "display-message":
                return 0, "$12 %34 1234567890"
            if args[0] == "has-session":
                return 0, ""  # attachment/respawn raced with the probe: seat is still here
            return 0, ""
        with patch.object(orch, "tmux_out", side_effect=tmux):
            self.assertFalse(orch.retire_exited("dead"))
        conditional = next(args for args in calls if args[0] == "if-shell")
        for field in ("pane_dead", "session_attached", "window_panes", "session_windows", "@ak_orch",
                      "session_id", "pane_id", "pane_dead_time"):
            self.assertIn(field, conditional[-2])
        self.assertEqual(conditional[-1], "kill-session -t =dead")


if __name__ == "__main__":
    unittest.main(verbosity=2)
