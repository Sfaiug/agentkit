"""A gone Claude session's scratch goes a day after it ended, while headless workers run.

Offline: /tmp, /proc and HOME are fixture-owned and the clock is injected.  A seat is named
by its pid record, a headless turn by its stdout, the event stream ak launched it writing to,
and a client neither names keeps only its own working directory's project.
"""

import json
import os
from pathlib import Path
import stat
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gc, orch, retention
from agentkit.harness import claude

DAY = 86400


class ScratchWithWorkers(Sandbox):
    def setUp(self):
        self.now = time.time() + 1
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(config, "JOBS", self.root / "jobs"))
        self.stack.enter_context(patch.object(retention, "unix_sockets", return_value=set()))
        self.tmp = self.root / "tmp-base"
        self.tmp.mkdir()
        self.stack.enter_context(patch.object(gc, "TMP_BASE", self.tmp))
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", self.proc.iterdir))
        self.stack.enter_context(patch.object(gc, "tmp_hidden_processes", return_value=None))
        self.seat_cwd, self.worker_cwd = self.root / "acme", self.root / "wt" / "fix-api"
        for cwd in (self.seat_cwd, self.worker_cwd):
            cwd.mkdir(parents=True)

    def process(self, args, cwd, opened=()):
        proc = self.proc / str(1000 + len(list(self.proc.iterdir())))
        (proc / "fd").mkdir(parents=True)
        fields = ["S", "1", *(["0"] * 18)]
        fields[19] = "12345"
        (proc / "stat").write_text(f"{proc.name} (fixture) " + " ".join(fields))
        (proc / "status").write_text("Uid:\t" + "\t".join([str(os.getuid())] * 4) + "\n")
        (proc / "cmdline").write_bytes(b"\0".join(os.fsencode(arg) for arg in args))
        (proc / "cwd").symlink_to(cwd)
        for index, path in enumerate(opened):
            (proc / "fd" / str(index)).symlink_to(path)
        return proc

    def seat(self, session):
        proc = self.process(["claude", "--resume", "before-clear"], self.seat_cwd)
        sessions = self.root / ".claude" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{proc.name}.json").write_text(json.dumps(
            {"pid": int(proc.name), "procStart": "12345", "sessionId": session}))

    def worker(self, session=None):
        """A headless turn as worker.call launches it: its stdout is the turn's event stream."""
        out = self.root / ".agentkit" / "runs" / "fix-api" / "round-1" / "executor"
        out.mkdir(parents=True)
        events = out / "events.jsonl"
        events.write_text("" if session is None else json.dumps(
            {"type": "system", "subtype": "init", "session_id": session}) + "\n")
        self.process(["claude", "-p", "--model", "opus", "--output-format", "stream-json"],
                     self.worker_cwd, opened=[out / "prompt.md", events, out / "stderr.log"])

    def scratch(self, cwd, session, folder=None):
        path = self.tmp / f"claude-{os.getuid()}" / (folder or claude.project(cwd)) / session
        path.mkdir(parents=True)
        (path / "tasks").mkdir()
        (path / "tasks" / "b1.output").write_text("temp\n")
        return path

    def planned(self):
        return {item["path"] for item in gc.gc_plan()
                if item["kind"] in ("tmp-entry", "claude-session")}

    def collect(self):
        planned = self.planned()
        gc.gc(lambda _: None)
        return planned

    def test_gone_sessions_go_while_a_headless_worker_runs(self):
        live_seat = self.scratch(self.seat_cwd, "sess-seat")
        live_worker = self.scratch(self.worker_cwd, "sess-worker")
        gone = {self.scratch(self.seat_cwd, "sess-ended"),
                self.scratch(self.worker_cwd, "sess-earlier-turn")}
        self.seat("sess-seat")
        self.worker("sess-worker")
        self.now += DAY + 3600
        self.assertEqual(self.collect(), set(map(str, gone)))
        self.assertFalse(any(path.exists() for path in gone))
        self.assertTrue(live_seat.is_dir())
        self.assertTrue(live_worker.is_dir())

    def test_an_unnamed_client_keeps_only_its_own_project(self):
        # A turn whose stream has not named its session yet, as just after launch.
        own = self.scratch(self.worker_cwd, "sess-resumed")
        elsewhere = self.scratch(self.seat_cwd, "sess-ended")
        self.worker()
        self.now += DAY + 3600
        self.assertEqual(self.collect(), {str(elsewhere)})
        self.assertFalse(elsewhere.exists())
        self.assertTrue(own.is_dir())

    def test_a_stream_a_client_only_reads_names_nothing(self):
        own = self.scratch(self.worker_cwd, "sess-resumed")
        elsewhere = self.scratch(self.seat_cwd, "sess-ended")
        earlier = self.root / "earlier-turn" / "events.jsonl"
        earlier.parent.mkdir()
        earlier.write_text(json.dumps({"type": "system", "session_id": "sess-ended"}) + "\n")
        self.process(["claude", "-p"], self.worker_cwd,
                     opened=[self.root / "prompt.md", self.root / "turn.log",
                             self.root / "stderr.log", earlier])
        self.now += DAY + 3600
        self.assertEqual(self.collect(), {str(elsewhere)})
        self.assertTrue(own.is_dir())

    def test_an_unnamed_client_keeps_its_project_as_claude_names_it(self):
        # Claude Code counts UTF-16 units and ends a long name with a hash of the whole path,
        # so a sibling under the same long parent is another project.
        rocket, shared = self.root / "acme-\U0001f680", "/work/" + "/".join(["acme" * 12] * 4)
        start = shared.replace("/", "-")[:200]
        kept = [self.scratch(rocket, "sess-resumed", claude.project(self.root) + "-acme---"),
                self.scratch(None, "sess-resumed", start + "-vqsc51")]
        gone = {self.scratch(self.seat_cwd, "sess-ended"),
                self.scratch(None, "sess-ended", start + "-kz5527")}
        rocket.mkdir()
        self.process(["claude"], rocket)
        self.process(["claude"], shared + "/active")
        self.now += DAY + 3600
        self.assertEqual(self.collect(), set(map(str, gone)))
        self.assertTrue(all(path.is_dir() for path in kept))

    def test_a_directory_change_time_alone_keeps_nothing(self):
        live_seat = self.scratch(self.seat_cwd, "sess-seat")
        gone = self.scratch(self.seat_cwd, "sess-ended")
        self.seat("sess-seat")
        self.now += DAY + 3600
        original = Path.lstat

        def restored(path, *args, **kwargs):
            # systemd-tmpfiles-clean puts each directory's times back, moving its change time.
            info = original(path, *args, **kwargs)
            if not stat.S_ISDIR(info.st_mode):
                return info
            fields = list(info)
            fields[9] = self.now
            return os.stat_result(fields)

        with patch.object(Path, "lstat", restored):
            self.assertEqual(self.collect(), {str(gone)})
        self.assertFalse(gone.exists())
        self.assertTrue(live_seat.is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
