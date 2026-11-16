"""The edges of a seat's look by the warm looker (`agentkit/looker.py`).

A census that could not be read authorizes no completion nudge; the looker's census serves every
decision the look makes, the usage wait and the account's settlement too; a looker installed over
while it read, or handed an event heard under other adapters, refuses it; and one orphaned as it
starts leaves the current socket be.
"""

import inspect
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from agentkit import config, menu, watch, warm
import test_harness_stop_parity as stop_fixture


class ReviewEdges(unittest.TestCase):
    def fixture(self, harness="muse"):
        owner = stop_fixture.StopParity()
        f = owner.seat(harness)
        self.addCleanup(owner.doCleanups)
        return owner, f

    def test_unreadable_run_census_cannot_start_another_turn(self):
        owner, f = self.fixture()
        f.receipt("20261113-1000-fix-api", "acme-api", "running")
        scandir = os.scandir

        def unreadable(path):
            if Path(path) == config.RUNS:
                raise PermissionError("run census is temporarily unreadable")
            return scandir(path)

        with patch.object(os, "scandir", side_effect=unreadable):
            try:
                owner.look(f)
            except PermissionError:
                pass  # A refused look is safe; an unreadable census proves no run absent.
        self.assertEqual(f.sent, [], "a failed census must not become evidence that no run is going")

    def test_a_supplied_census_serves_the_usage_wait_decision_too(self):
        owner, f = self.fixture("claude")
        config.plan_path("acme-api").write_text("- [x] acme parser works\n")
        watch.seat_write("acme-api", usage_wait={
            "reason": "anthropic out of usage", "until": 20000,
            "since": 10000, "continue": False})
        directory = config.RUNS / "20261113-1000-fix-api"
        directory.mkdir()
        (directory / "run.json").write_text('{"state":"pass","launched_session":"other"}')
        records = menu.run_records(cache=False, rest_may_lag=True)
        # Record the full scans, not elapsed time.  This is what a fork inherits.
        scandir, reads = os.scandir, []

        def reading(path):
            if Path(path) == config.RUNS:
                reads.append(str(path))
            return scandir(path)

        with patch.object(os, "scandir", side_effect=reading):
            if "records" in inspect.signature(watch.hook_look).parameters:
                owner.look(f, records=records)
            else:
                owner.look(f)
        self.assertEqual(reads, [], "the hook's decisions must use its handed-in census")

    def test_a_supplied_census_serves_account_settlement_too(self):
        from test_limit_moves_at_once import LimitMovesAtOnce, NAME, LIMIT
        f = LimitMovesAtOnce()
        f.setUp()
        self.addCleanup(f.doCleanups)
        os.environ.update(TMUX="/tmp/acme-socket,1,0", TMUX_PANE="%1")
        config.plan_path(NAME).write_text("- [x] acme parser works\n")
        f.pane = f"● {LIMIT}\n❯"
        f.fact("StopFailure")
        records = menu.run_records(cache=False, rest_may_lag=True)
        scandir, reads = os.scandir, []

        def reading(path):
            if Path(path) == config.RUNS:
                reads.append(str(path))
            return scandir(path)

        with patch.object(watch, "recorded_error", return_value=LIMIT), \
                patch.object(os, "scandir", side_effect=reading):
            if "records" in inspect.signature(watch.hook_look).parameters:
                watch.hook_look(NAME, records=records)
            else:
                watch.hook_look(NAME)
        self.assertEqual(reads, [], "settling the account must use the looker's census too")

    def test_an_empty_supplied_census_serves_the_usage_wait_decision_too(self):
        owner, f = self.fixture("claude")
        config.plan_path("acme-api").write_text("- [x] acme parser works\n")
        watch.seat_write("acme-api", usage_wait={
            "reason": "anthropic out of usage", "until": 20000,
            "since": 10000, "continue": False})
        # An empty filtered result can still stand for a large HOME's census.
        for number in range(40):
            directory = config.RUNS / f"20261113-{number:04d}-fix-api"
            directory.mkdir()
            (directory / "run.json").write_text(json.dumps({
                "state": "pass", "launched_session": "other", "unattended": True}))
        records = menu.run_records(cache=False, rest_may_lag=True)
        self.assertEqual(records, [])
        scandir, reads = os.scandir, []

        def reading(path):
            if Path(path) == config.RUNS:
                reads.append(str(path))
            return scandir(path)

        with patch.object(os, "scandir", side_effect=reading):
            if "records" in inspect.signature(watch.hook_look).parameters:
                owner.look(f, records=records)
            else:
                owner.look(f)
        self.assertEqual(reads, [], "a successful empty census must not trigger another full scan")


class LookerLifecycle(unittest.TestCase):
    def setUp(self):
        try:
            from agentkit import looker
        except ImportError:
            self.skipTest("base always looks cold and has no looker lifecycle")
        self.looker = looker
        tmp = tempfile.TemporaryDirectory(prefix=".ak-review-looker-", dir=Path(__file__).resolve().parents[1])
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for p in (patch.dict(os.environ, {"HOME": str(self.root)}),
                  patch.object(config, "HOME", self.root / ".agentkit"),
                  patch.object(warm, "_resident", lambda: None)):
            p.start()
            self.addCleanup(p.stop)
        config.ensure_dirs()
        self.name = warm.place(str(config.REPO))[1] + ".look"

    def pipes(self):
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        self.addCleanup(os.close, w)
        return r, w

    def start(self, read, parent=None):
        pid = os.fork()
        if pid == 0:
            try:
                with patch.object(menu, "run_records", side_effect=read):
                    if parent is not None:
                        with patch.object(os, "getppid", side_effect=parent):
                            self.looker.serve()
                    else:
                        self.looker.serve()
            finally:
                os._exit(1)

        def finish():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        self.addCleanup(finish)
        return pid

    def connect(self):
        before = os.open(".", os.O_RDONLY)
        os.chdir(config.STATE)
        try:
            while True:
                conn = socket.socket(socket.AF_UNIX)
                try:
                    conn.connect(self.name)
                    return conn
                except (FileNotFoundError, ConnectionRefusedError):
                    conn.close()
                    time.sleep(0.01)
        finally:
            os.fchdir(before)
            os.close(before)

    def test_an_install_during_the_census_is_refused_before_ready(self):
        reached_r, reached_w = self.pipes()
        gate_r, gate_w = self.pipes()
        calls = 0

        def read(**_kw):
            nonlocal calls
            calls += 1
            if calls == 2:
                os.write(reached_w, b"r")
                os.read(gate_r, 1)
            return []

        self.start(read)
        conn = self.connect()
        try:
            self.assertEqual(os.read(reached_r, 1), b"r")
            (config.STATE / "installed-at").write_text(str(time.time()))
            data = b"\0".join((b"acme-api", b"", b"UserPromptSubmit", b"go", b"0",
                               b"TMUX=/fake/acme,1,0", b"TMUX_PANE=%7"))
            conn.sendall(len(data).to_bytes(4, "big") + data)
            os.write(gate_w, b"g")
            try:
                ready = conn.recv(1)
            except (ConnectionAbortedError, ConnectionResetError):
                ready = b""
        finally:
            conn.close()
        self.assertNotEqual(ready, b"R", "code older than the install must refuse the event")

    def test_an_event_heard_under_other_adapters_is_refused_before_ready(self):
        mine = str(self.root / "adapters")
        p = patch.dict(os.environ, {config.ADAPTER_DIR_ENV: mine})
        p.start()
        self.addCleanup(p.stop)
        self.start(lambda **_kw: [])

        def ready(adapters):
            conn = self.connect()
            try:
                data = b"\0".join((b"acme-api", b"", b"Notification", b"", b"2",
                                   b"permission_prompt", b"", b"TMUX=/fake/acme,1,0",
                                   b"TMUX_PANE=%7", f"{config.ADAPTER_DIR_ENV}={adapters}".encode()))
                conn.sendall(len(data).to_bytes(4, "big") + data)
                try:
                    return conn.recv(1)
                except (ConnectionAbortedError, ConnectionResetError):
                    return b""
            finally:
                conn.close()        # never told go: the child leaves without a look
        self.assertEqual(ready(mine), b"R", "the looker's own adapters are its to hear")
        self.assertNotEqual(ready(str(self.root / "other")), b"R",
                            "what an event means is the hook's adapters' to say: it goes cold")

    def test_an_orphan_finishing_startup_cannot_replace_the_current_socket(self):
        reached_r, reached_w = self.pipes()
        gate_r, gate_w = self.pipes()
        orphaned = self.root / "orphaned"

        def initial_read(**_kw):
            os.write(reached_w, b"r")
            os.read(gate_r, 1)
            return []

        old = self.start(initial_read, lambda: 1 if orphaned.exists() else 4242)
        self.assertEqual(os.read(reached_r, 1), b"r")
        self.start(lambda **_kw: [])
        conn = self.connect()
        conn.close()
        current = (config.STATE / self.name).stat().st_ino
        orphaned.touch()
        os.write(gate_w, b"g")
        os.waitpid(old, 0)
        self.assertEqual((config.STATE / self.name).stat().st_ino, current,
                         "the old looker unlinked the live looker's socket before noticing its parent left")

    def test_start_look_waits_for_the_warm_look_in_a_session_of_its_own(self):
        entered_r, entered_w = self.pipes()
        release_r, release_w = self.pipes()
        done = self.root / "warm-acme-api"

        def warm_look(seat, *_args, **_kw):
            os.write(entered_w, b"l")
            os.read(release_r, 1)
            done.write_text(seat)

        with patch.object(self.looker, "look", side_effect=warm_look):
            self.start(lambda **_kw: [])
        self.connect().close()
        with patch.dict(os.environ, {"TMUX": "/fake/acme,1,0", "TMUX_PANE": "%7"}):
            proc = watch.start_look("acme-api")
        self.assertIsNotNone(proc)
        self.addCleanup(proc.wait)
        self.assertEqual(os.read(entered_r, 1), b"l")
        self.assertEqual(os.getsid(proc.pid), proc.pid)
        self.assertIsNone(proc.poll(), "the caller's wait must hold until the warm look finishes")
        os.write(release_w, b"g")
        self.assertEqual(proc.wait(timeout=30), 0)
        self.assertEqual(done.read_text(), "acme-api")


if __name__ == "__main__":
    unittest.main()
