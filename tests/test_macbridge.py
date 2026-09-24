"""Offline Mac -> VM bridge regressions; all files and processes are isolated here."""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import plistlib
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, macbridge, menu


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".macbridge-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "TMPDIR": str(self.root), "AK_FETCH_TIMEOUT": "3",
        }))
        # The bridge reaches the recorded server, never a literal alias: a fixture value
        # here proves every ssh/scp call site reads it.
        self.stack.enter_context(patch.object(config, "server_alias", return_value="myserver"))
        self.bridge = self.root / ".agentkit/macbridge"

    def command(self, *args, **kwargs):
        return subprocess.run([sys.executable, str(REPO / "bin/ak"), *args],
                              text=True, capture_output=True, timeout=8, **kwargs)

    def process(self, *args):
        return self.spawn([sys.executable, str(REPO / "bin/ak"), *args])

    def serve(self, timeout=0.5):
        # Assigning the timeout also works on the old module, where it is ignored.
        return self.spawn([sys.executable, "-c",
                           "from agentkit import macbridge; "
                           f"macbridge.HEARTBEAT_TIMEOUT = {timeout!r}; "
                           "raise SystemExit(macbridge.fetch_main(['--serve']))"])

    def spawn(self, args):
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd=REPO)

        def cleanup():
            if proc.poll() is None:
                proc.kill()
            for name in ("stdin", "stdout", "stderr"):
                pipe = getattr(proc, name)
                if pipe is not None and pipe.closed:
                    setattr(proc, name, None)
            proc.communicate(timeout=3)
        self.addCleanup(cleanup)
        return proc

    def requests(self, count=1):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            paths = list((self.bridge / "requests").glob("[a-f0-9]*"))
            if len(paths) == count:
                return paths
            time.sleep(0.01)
        self.fail(f"did not find {count} requests")

    def line(self, proc):
        self.assertTrue(select.select([proc.stdout], [], [], 3)[0], "server did not flush")
        return proc.stdout.readline().rstrip("\n").split("\t", 1)

    def request(self, path="/Users/me/logo.png", ident="0123456789abcdef"):
        request = macbridge.directories() / "requests" / ident
        temp = request.with_name(f".{ident}.tmp")
        temp.write_text(json.dumps({"path": path}))
        temp.replace(request)
        return request

    def heartbeat(self, server):
        server.stdin.write("heartbeat\n")
        server.stdin.flush()


class Fetch(Sandbox):
    def test_serve_exits_when_sshd_holds_stdin_open_without_heartbeats(self):
        request = self.request()
        server = self.serve()
        # Both pipe ends remain open, just as with a half-open sshd session. In
        # particular, communicate() would close stdin and hide the actual bug.
        self.assertEqual(server.wait(timeout=2), 0)
        self.assertFalse(server.stdin.closed)
        self.assertFalse(server.stdout.closed)
        self.assertEqual(server.stdout.read(), "")
        self.assertTrue(request.exists())

    def test_heartbeats_keep_serve_alive_then_expire_and_release_the_lock(self):
        server = self.serve()
        for _ in range(8):
            self.heartbeat(server)
            time.sleep(0.1)
            self.assertIsNone(server.poll())
        self.assertEqual(server.wait(timeout=2), 0)
        # A new connection can take over after expiry and hand off queued work.
        request = self.request()
        replacement = self.serve()
        self.heartbeat(replacement)
        self.assertEqual(self.line(replacement), [request.name, "/Users/me/logo.png"])
        out, err = replacement.communicate(timeout=2)
        self.assertEqual(replacement.returncode, 0, err)
        self.assertEqual(out, "")
        self.assertFalse(request.exists())

    def test_only_complete_heartbeat_lines_extend_the_deadline(self):
        server = self.serve()
        server.stdin.write("heart")
        server.stdin.flush()
        time.sleep(0.15)
        server.stdin.write("beat\nheartbeat\n")
        server.stdin.flush()
        # Invalid traffic must not renew the peer lease, even with an oversized
        # partial line. The valid, fragmented beat above does enable delivery.
        request = self.request()
        self.assertEqual(self.line(server), [request.name, "/Users/me/logo.png"])
        deadline = time.monotonic() + 2
        while server.poll() is None and time.monotonic() < deadline:
            try:
                server.stdin.write("x" * 2048)
                server.stdin.flush()
            except BrokenPipeError:
                break
            time.sleep(0.1)
        self.assertEqual(server.wait(timeout=1), 0)

    def test_broken_stdout_keeps_request_for_the_next_serve(self):
        request = self.request()
        server = self.serve()
        server.stdout.close()
        self.heartbeat(server)
        self.assertEqual(server.wait(timeout=2), 0)
        self.assertTrue(request.exists())
        replacement = self.serve()
        self.heartbeat(replacement)
        self.assertEqual(self.line(replacement), [request.name, "/Users/me/logo.png"])
        out, err = replacement.communicate(timeout=2)
        self.assertEqual(replacement.returncode, 0, err)
        self.assertEqual(out, "")
        self.assertFalse(request.exists())

    def test_full_stdout_cannot_prevent_expiry_and_partial_request_is_retained(self):
        # Larger than a pipe even on systems with dynamically growing buffers.
        path = "/Users/me/" + "x" * (2 * 1024 * 1024)
        request = self.request(path)
        server = self.serve(timeout=0.8)
        self.heartbeat(server)
        self.assertTrue(select.select([server.stdout], [], [], 2)[0])
        self.assertTrue(request.exists(), "dequeued before the line was fully written")
        # Keep stdout's reader open but do not drain it: the writer must continue
        # checking its heartbeat while the pipe is full.
        self.assertEqual(server.wait(timeout=2), 0)
        partial = server.stdout.read()
        self.assertTrue(partial.startswith(request.name + "\t"))
        self.assertFalse(partial.endswith("\n"))
        self.assertTrue(request.exists())
        replacement = self.serve(timeout=5)
        self.heartbeat(replacement)
        self.assertEqual(self.line(replacement), [request.name, path])
        out, err = replacement.communicate(timeout=2)
        self.assertEqual(replacement.returncode, 0, err)
        self.assertEqual(out, "")
        self.assertFalse(request.exists())

    def test_only_one_live_server_consumes_each_request_once(self):
        root = macbridge.directories()
        servers = [self.serve(timeout=5) for _ in range(2)]
        for server in servers:
            try:
                self.heartbeat(server)
            except BrokenPipeError:  # the lock loser may already have exited
                pass
        deadline = time.monotonic() + 2
        while all(server.poll() is None for server in servers) and time.monotonic() < deadline:
            time.sleep(0.01)
        consumers = [server for server in servers if server.poll() is None]
        self.assertEqual(len(consumers), 1, "both serves still hold consumer connections")
        consumer, = consumers
        other = next(server for server in servers if server is not consumer)
        self.assertEqual(other.returncode, 0)
        self.assertEqual(other.stdout.read(), "")
        self.assertIn("another connection holds serve.lock", other.stderr.read())
        # Publish after contention settles: the old per-scan lock can deliver
        # each id once, but still leaves two competing consumers alive.
        ids = [f"{n:016x}" for n in range(8)]
        lines = []
        for ident in ids:
            path = f"/Users/me/{ident}.png"
            self.request(path, ident)
            lines.append(self.line(consumer))
        out, err = consumer.communicate(timeout=2)
        self.assertEqual(consumer.returncode, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(lines, [[ident, f"/Users/me/{ident}.png"] for ident in ids])
        self.assertFalse(list((root / "requests").glob("[a-f0-9]*")))

    def test_existing_quoted_escaped_relative_and_symlink_paths(self):
        path = self.root / "owner's $logo (one).png"
        path.write_bytes(b"image")
        link = self.root / "link.png"
        link.symlink_to(path)
        escaped = str(path).replace(" ", "\\ ").replace("(", "\\(").replace(")", "\\)")
        args = [str(path), shlex.quote(str(path)), escaped, str(link), path.name]
        proc = self.command("fetch", *args, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), [str(path)] * 3 + [str(link), str(path)])
        self.assertFalse(self.bridge.exists())

    def test_timeout_enqueues_normalized_request_then_cleans_up(self):
        with patch.dict(os.environ, {"AK_FETCH_TIMEOUT": "0.3"}):
            proc = self.process("fetch", "'/Users/me/Desktop/screen\\ shot.png'")
        request, = self.requests()
        self.assertEqual(json.loads(request.read_text()), {
            "path": "/Users/me/Desktop/screen shot.png", "basename": "screen_shot.png",
        })
        out, err = proc.communicate(timeout=3)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(out, "")
        self.assertIn("no answer from the Mac bridge in 0.3s; the Mac may be asleep or offline, "
                      "or ak macbridge is not running there (open ak on the Mac)", err)
        self.assertFalse(request.exists())

    def test_pending_and_new_requests_flush_and_inbox_drop_resolves(self):
        pasted = "/var/folders/ab/TemporaryItems/NSIRD_screencaptureui_ab12/Screenshot 2026.png"
        fetch = self.process("fetch", pasted, "/Users/me/logo.svg")
        request, = self.requests()
        server = self.process("fetch", "--serve")
        server.stdin.write("heartbeat\n")
        server.stdin.flush()
        ident, path = self.line(server)
        self.assertEqual(path, pasted)
        self.assertEqual(request.name, ident)
        # The complete write must precede unlink, so the reader can wake first.
        deadline = time.monotonic() + 2
        while request.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(request.exists())
        partial = self.bridge / "inbox" / f".{ident}.part"
        partial.write_bytes(b"partial")
        time.sleep(0.15)
        self.assertIsNone(fetch.poll())
        dest = self.bridge / "inbox" / f"{ident}.png"
        partial.write_bytes(b"complete image")
        partial.rename(dest)
        ident2, path2 = self.line(server)
        self.assertEqual(path2, "/Users/me/logo.svg")
        dest2 = self.bridge / "inbox" / f"{ident2}.svg"
        dest2.write_text("<svg/>")
        out, err = fetch.communicate(timeout=3)
        self.assertEqual(fetch.returncode, 0, err)
        self.assertEqual(out.splitlines(), [str(dest), str(dest2)])
        self.assertEqual(dest.read_bytes(), b"complete image")
        server.stdin.close()
        server.stdin = None
        self.assertEqual(server.wait(timeout=3), 0)

    def test_two_servers_do_not_duplicate_requests_and_exit_on_eof(self):
        root = macbridge.directories()
        ids = {f"{n:016x}" for n in range(8)}
        for ident in ids:
            (root / "requests" / ident).write_text(json.dumps({"path": f"/Users/me/{ident}.png"}))
        servers = [self.process("fetch", "--serve") for _ in range(2)]
        for server in servers:
            try:
                self.heartbeat(server)
            except BrokenPipeError:  # the lock loser may already have exited
                pass
        deadline = time.monotonic() + 3
        while list((root / "requests").glob("[a-f0-9]*")) and time.monotonic() < deadline:
            time.sleep(0.01)
        lines = []
        for server in servers:
            out, err = server.communicate(timeout=3)
            self.assertEqual(server.returncode, 0, err)
            lines.extend(out.splitlines())
        self.assertEqual(len(lines), len(ids))
        self.assertEqual({line.split("\t")[0] for line in lines}, ids)

    def test_missing_marker_stops_wait_and_other_paths_still_print(self):
        local = self.root / "local"
        local.touch()
        fetch = self.process("fetch", "/Users/me/gone.png", str(local))
        request, = self.requests()
        (self.bridge / "inbox" / f"{request.name}.missing").touch()
        out, err = fetch.communicate(timeout=3)
        self.assertEqual(fetch.returncode, 1)
        self.assertIn("the Mac no longer has that file", err)
        self.assertEqual(out, f"{local}\n")

    def test_empty_missing_extension_file_is_not_a_failure(self):
        fetch = self.process("fetch", "/Users/me/empty.missing")
        request, = self.requests()
        (self.bridge / "inbox" / f".{request.name}.ready").touch()
        dest = self.bridge / "inbox" / f"{request.name}.missing"
        dest.touch()
        out, err = fetch.communicate(timeout=3)
        self.assertEqual(fetch.returncode, 0, err)
        self.assertEqual(out, f"{dest}\n")

    def test_error_marker_fails_immediately_with_its_reason_and_is_removed(self):
        ident = "0123456789abcdef"
        root = macbridge.directories()
        marker = root / "inbox" / f".{ident}.error"
        path = "/Users/me/screenshot.png"
        for text in ("scp: Operation not permitted\n", "", "\n"):
            with self.subTest(text=text):
                marker.write_text(text)
                with patch.object(macbridge.secrets, "token_hex", return_value=ident), \
                        patch.object(macbridge.time, "sleep", side_effect=AssertionError("waited")):
                    with self.assertRaises(config.Error) as error:
                        macbridge.fetch_one(path, 25)
                reason = text.strip() or "the Mac could not send that file"
                self.assertEqual(str(error.exception), f"{path}: {reason}")
                self.assertFalse(marker.exists())
                self.assertEqual(list((root / "requests").iterdir()), [])

    def test_error_extension_is_a_delivery_and_error_part_is_not_a_marker(self):
        fetch = self.process("fetch", "/Users/me/file.error")
        request, = self.requests()
        (self.bridge / "inbox" / f".{request.name}.error.part").write_text("unfinished")
        time.sleep(0.15)
        self.assertIsNone(fetch.poll())
        dest = self.bridge / "inbox" / f"{request.name}.error"
        dest.touch()
        out, err = fetch.communicate(timeout=3)
        self.assertEqual(fetch.returncode, 0, err)
        self.assertEqual(out, f"{dest}\n")
        self.assertTrue(dest.exists())

    def test_ready_extension_and_long_basename_preserve_the_delivered_file(self):
        self.assertEqual(macbridge.extension("/Users/me/" + "x" * 240 + ".png"), ".png")
        fetch = self.process("fetch", "/Users/me/file.ready")
        request, = self.requests()
        dest = self.bridge / "inbox" / f"{request.name}.ready"
        dest.touch()
        out, err = fetch.communicate(timeout=3)
        self.assertEqual(fetch.returncode, 0, err)
        self.assertEqual(out, f"{dest}\n")
        self.assertTrue(dest.exists())

    def test_bad_timeout_and_unrepresentable_paths_fail_without_waiting(self):
        for value in ("nan", "inf", "-1", "wrong"):
            with self.subTest(value=value), patch.dict(os.environ, {"AK_FETCH_TIMEOUT": value}):
                proc = self.command("fetch", "/Users/me/file.png")
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("AK_FETCH_TIMEOUT", proc.stderr)
        for value in ("", "/Users/me/tab\tfile.png", "/Users/me/new\nline.png"):
            self.assertNotEqual(self.command("fetch", value).returncode, 0)
        self.assertFalse(self.bridge.exists())


class Reader(Sandbox):
    def test_app_is_the_topmost_ancestor_below_launchd(self):
        with patch.object(macbridge.os, "getpid", return_value=500), \
                patch.object(macbridge.subprocess, "run", side_effect=[
                    Mock(stdout=" 400\n"), Mock(stdout=" 300\n"), Mock(stdout=" 1\n"),
                ]) as call:
            self.assertEqual(macbridge.terminal_app_pid(), 300)
        self.assertEqual([args.args[0] for args in call.call_args_list], [
            ["ps", "-o", "ppid=", "-p", str(pid)] for pid in (500, 400, 300)])

    def test_reader_copies_readable_request_and_leaves_unreadable_and_missing(self):
        root = macbridge.directories()
        readable = self.root / "screen shot.png"
        readable.write_bytes(b"screenshot data")
        unreadable = self.root / "another app.png"
        unreadable.write_bytes(b"private")
        unreadable.chmod(0)
        self.addCleanup(unreadable.chmod, 0o600)
        requests = []
        for index, path in enumerate((readable, unreadable, self.root / "gone.png")):
            request = root / "reads" / f"{index:016x}"
            request.write_text(json.dumps({"path": str(path)}))
            requests.append(request)
        ignored = root / "reads" / ".unfinished.tmp"
        ignored.write_text("half written")
        lockpath = root / "reader-300.lock"
        with macbridge.acquire_lock(lockpath.name), \
                patch.object(macbridge.os, "kill", side_effect=[None, ProcessLookupError]) as kill, \
                patch.object(macbridge.time, "sleep") as sleep:
            macbridge.reader_loop(root, 300, io.StringIO())
        self.assertEqual((root / "staged" / requests[0].name).read_bytes(), b"screenshot data")
        self.assertFalse(requests[0].exists())
        self.assertTrue(requests[1].exists())
        self.assertTrue(requests[2].exists())
        self.assertTrue(ignored.exists())
        self.assertEqual(len(list((root / "staged").iterdir())), 1)
        self.assertEqual([call.args for call in kill.call_args_list], [(300, 0), (300, 0)])
        sleep.assert_called_once_with(macbridge.POLL)
        self.assertFalse(lockpath.exists())

    def test_reader_exits_before_reading_when_app_is_gone(self):
        root = macbridge.directories()
        request = root / "reads" / "0123456789abcdef"
        request.write_text(json.dumps({"path": str(self.root / "file")}))
        with macbridge.acquire_lock("reader-300.lock"), \
                patch.object(macbridge.os, "kill", side_effect=ProcessLookupError), \
                patch.object(macbridge.time, "sleep") as sleep:
            macbridge.reader_loop(root, 300, io.StringIO())
        sleep.assert_not_called()
        self.assertTrue(request.exists())
        self.assertFalse((root / "reader-300.lock").exists())

    def test_reader_discards_partial_copy_after_cancellation_or_copy_failure(self):
        root = macbridge.directories()
        source = self.root / "screenshot.png"
        source.write_bytes(b"image")
        request = root / "reads" / "0123456789abcdef"

        def copy(source, target):
            target.write(b"partial")
            if fail:
                raise OSError("read failed")
            request.unlink()  # The bridge timed out while the copy was in progress.

        for fail in (True, False):
            with self.subTest(fail=fail):
                request.write_text(json.dumps({"path": str(source)}))
                with patch.object(macbridge.os, "kill", side_effect=[None, ProcessLookupError]), \
                        patch.object(macbridge.time, "sleep"), \
                        patch.object(macbridge.shutil, "copyfileobj", side_effect=copy):
                    macbridge.reader_loop(root, 300, io.StringIO())
                self.assertEqual(list((root / "staged").iterdir()), [])
                self.assertEqual(request.exists(), fail)

    def test_reader_command_detaches_once_per_app_and_hands_lock_across_exec(self):
        inherited = []

        def spawn(argv, **kwargs):
            inherited.append(os.dup(kwargs["pass_fds"][0]))
            self.assertEqual(argv[2:6], ["macbridge", "--reader", "--app-pid", str(apppid)])
            self.assertEqual(argv[6:], ["--lock-fd", str(kwargs["pass_fds"][0])])
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(Path(kwargs["stdout"].name), self.bridge / "macbridge.log")
            self.assertIs(kwargs["stdout"], kwargs["stderr"])

        with patch.object(macbridge.sys, "platform", "darwin"), \
                patch.object(macbridge, "terminal_app_pid", side_effect=lambda: apppid), \
                patch.object(macbridge.subprocess, "Popen", side_effect=spawn) as call:
            try:
                for apppid in (300, 300, 400):
                    self.assertEqual(macbridge.main(["--reader"]), 0)
                self.assertEqual(call.call_count, 2)
                self.assertIsNone(macbridge.acquire_lock("reader-300.lock"))
                self.assertIsNone(macbridge.acquire_lock("reader-400.lock"))
            finally:
                for fd in inherited:
                    os.close(fd)

    def test_detached_reader_uses_passed_app_pid_and_releases_lock_on_exit(self):
        lock = macbridge.acquire_lock("reader-300.lock")
        inherited = os.dup(lock.fileno())
        lock.close()
        os.set_inheritable(inherited, True)
        with patch.object(macbridge.sys, "platform", "darwin"), \
                patch.object(macbridge.os, "kill", side_effect=ProcessLookupError) as kill, \
                patch.object(macbridge, "terminal_app_pid", side_effect=AssertionError("rediscovered")), \
                patch.object(macbridge, "bridge_loop", side_effect=AssertionError("bridge started")):
            self.assertEqual(macbridge.main([
                "--reader", "--app-pid", "300", "--lock-fd", str(inherited)]), 0)
        kill.assert_called_once_with(300, 0)
        self.assertFalse((self.bridge / "reader-300.lock").exists())
        with self.assertRaises(OSError):
            os.fstat(inherited)

    def test_failed_spawn_cleans_up_reader_lock_and_unknown_arguments_fail(self):
        with patch.object(macbridge.sys, "platform", "darwin"), \
                patch.object(macbridge, "terminal_app_pid", return_value=300), \
                patch.object(macbridge.subprocess, "Popen", side_effect=OSError("spawn failed")):
            with self.assertRaisesRegex(config.Error, "spawn failed"):
                macbridge.main(["--reader"])
            self.assertFalse((self.bridge / "reader-300.lock").exists())
            for args in (["--bad"], ["--reader", "--bad"], ["extra"]):
                with self.subTest(args=args), self.assertRaises(config.Error) as error:
                    macbridge.main(args)
                self.assertEqual(str(error.exception), "usage: ak macbridge [--reader]")


class Mac(Sandbox):
    def test_bridge_heartbeats_continue_during_idle_reads_and_slow_transfers(self):
        server = self.serve(timeout=0.3)
        sender_threads = []
        errors = []
        send_heartbeats = macbridge.send_heartbeats

        def heartbeat(*args):
            sender_threads.append(threading.current_thread())
            send_heartbeats(*args)

        def publish_after_idle():
            # The bridge is blocked in stdout iteration until this arrives.
            threading.Event().wait(0.7)
            if server.poll() is not None:
                errors.append("serve expired while bridge was idle")
            self.request()

        publisher = threading.Thread(target=publish_after_idle)
        publisher.start()
        self.addCleanup(publisher.join)

        def slow_transfer(ident, path, options, log):
            threading.Event().wait(0.7)
            self.assertIsNone(server.poll(), "serve expired during a slow transfer")
            self.assertEqual((ident, path), ("0123456789abcdef", "/Users/me/logo.png"))
            raise KeyboardInterrupt

        with patch.object(macbridge.subprocess, "Popen", return_value=server) as spawn, \
                patch.object(macbridge, "HEARTBEAT_INTERVAL", 0.05), \
                patch.object(macbridge, "send_heartbeats", side_effect=heartbeat), \
                patch.object(macbridge, "transfer", side_effect=slow_transfer) as transfer, \
                patch.object(macbridge, "time", wraps=time) as clock:
            clock.sleep.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                macbridge.bridge_loop(self.root, io.StringIO())
        publisher.join()
        self.assertEqual(errors, [])
        transfer.assert_called_once()
        spawn.assert_called_once()
        self.assertTrue(server.stdin.closed)
        self.assertIsNotNone(server.poll())
        self.assertEqual(len(sender_threads), 1)
        self.assertFalse(sender_threads[0].is_alive())

    def test_heartbeat_sender_handles_a_full_pipe_and_a_closed_peer(self):
        read_fd, write_fd = os.pipe()
        reader = self.stack.enter_context(os.fdopen(read_fd, "rb"))
        writer = self.stack.enter_context(os.fdopen(write_fd, "wb"))
        os.set_blocking(write_fd, False)
        while True:
            try:
                os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                break
        stream = Mock(stdin=writer)
        stream.poll.return_value = None
        stopped = threading.Event()
        sender = threading.Thread(target=macbridge.send_heartbeats, args=(stream, stopped))
        sender.start()
        stopped.set()
        sender.join(timeout=2)
        self.assertFalse(sender.is_alive(), "heartbeat write blocked cleanup")
        stream.terminate.assert_not_called()
        reader.close()
        macbridge.send_heartbeats(stream, threading.Event())
        stream.terminate.assert_called_once()

    def test_bridge_discards_an_incomplete_request_on_stream_close(self):
        stream = Mock()
        stream.stdout = io.StringIO("0123456789abcdef\t/Users/me/partial")
        stream.stdin = self.stack.enter_context(tempfile.TemporaryFile(dir=self.root))
        stream.poll.return_value = 0
        log = io.StringIO()
        with patch.object(macbridge.subprocess, "Popen", return_value=stream), \
                patch.object(macbridge, "transfer") as transfer, \
                patch.object(macbridge.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                macbridge.bridge_loop(self.root, log)
        transfer.assert_not_called()
        self.assertIn("ignoring incomplete request", log.getvalue())

    def test_transfer_uses_shared_outbound_connection_and_atomic_publish(self):
        source = self.root / "my `logo` $(oops).PNG"
        source.write_bytes(b"logo")
        ident = "0123456789abcdef"
        options = macbridge.ssh_options(self.root)
        with patch.object(macbridge.subprocess, "run") as call:
            macbridge.transfer(ident, str(source), options, io.StringIO())
        scp, publish = call.call_args_list
        self.assertEqual(scp.args[0], ["scp", "-q", *options, "--", str(source),
                                      f"myserver:.agentkit/macbridge/inbox/.{ident}.part"])
        self.assertIn("ControlMaster=auto", options)
        self.assertIn("ControlPersist=60", options)
        self.assertEqual(publish.args[0][:len(options) + 3], ["ssh", *options, "-T", "myserver"])
        self.assertTrue(publish.args[0][-1].endswith(f"/{ident}.PNG"))
        self.assertNotIn(str(source), publish.args[0][-1])

    def test_missing_file_only_writes_zero_byte_marker_and_bad_id_is_rejected(self):
        with patch.object(macbridge.subprocess, "run") as call:
            macbridge.transfer("0123456789abcdef", "/Users/me/gone.png", [], io.StringIO())
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[0], ["ssh", "-T", "myserver",
                ': > "$HOME"/.agentkit/macbridge/inbox/0123456789abcdef.missing'])
            with self.assertRaises(ValueError):
                macbridge.transfer("../../escape", "/Users/me/file", [], io.StringIO())
            self.assertEqual(call.call_count, 1)

    def test_permission_probe_uses_reader_copy_and_cleans_up_even_on_scp_failure(self):
        root = macbridge.directories()
        source = self.root / "dropped screenshot.PNG"
        source.write_bytes(b"image")
        ident = "0123456789abcdef"
        staged = root / "staged" / ident
        options = macbridge.ssh_options(root)

        def read_request(seconds):
            self.assertEqual(seconds, macbridge.POLL)
            request = root / "reads" / ident
            self.assertEqual(json.loads(request.read_text()), {"path": str(source)})
            staged.write_bytes(b"staged image")
            request.unlink()

        def run(argv, **kwargs):
            if argv[0] == "scp":
                self.assertEqual(argv, ["scp", "-q", *options, "--", str(staged),
                                       f"myserver:.agentkit/macbridge/inbox/.{ident}.part"])
                self.assertEqual(staged.read_bytes(), b"staged image")
                if fail:
                    raise subprocess.CalledProcessError(1, argv)
            else:
                self.assertEqual(argv[:len(options) + 3], ["ssh", *options, "-T", "myserver"])
                self.assertTrue(argv[-1].endswith(f"/{ident}.PNG"))

        for fail in (False, True):
            with self.subTest(fail=fail), macbridge.acquire_lock("reader-300.lock"), \
                    patch("builtins.open", side_effect=PermissionError("Operation not permitted")) as probe, \
                    patch.object(macbridge.time, "sleep", side_effect=read_request) as sleep, \
                    patch.object(macbridge.subprocess, "run", side_effect=run) as call:
                if fail:
                    with self.assertRaises(subprocess.CalledProcessError):
                        macbridge.transfer(ident, str(source), options, io.StringIO())
                else:
                    macbridge.transfer(ident, str(source), options, io.StringIO())
                probe.assert_called_once_with(source, "rb")
                sleep.assert_called_once()
                self.assertEqual(call.call_count, 1 if fail else 2)
                self.assertFalse(staged.exists())
                self.assertEqual(list((root / "reads").iterdir()), [])
                self.assertIsNone(macbridge.acquire_lock("reader-300.lock"))

    def test_permission_without_live_reader_or_after_timeout_publishes_error_without_scp(self):
        root = macbridge.directories()
        source = self.root / "dropped.png"
        source.touch()
        ident = "0123456789abcdef"
        reason = ("macOS lets only the app the file was dropped on read it: open a new terminal tab "
                  "on the Mac (or run ak macbridge --reader there) and fetch again")
        for live in (False, True):
            with self.subTest(live=live), ExitStack() as stack:
                stale = root / "reader-200.lock"
                stale.touch()
                if live:
                    stack.enter_context(macbridge.acquire_lock("reader-300.lock"))
                stack.enter_context(patch("builtins.open", side_effect=PermissionError))
                call = stack.enter_context(patch.object(macbridge.subprocess, "run"))
                sleep = stack.enter_context(patch.object(macbridge.time, "sleep"))
                # One real poll, then a deadline 10 seconds after publication.
                clock = stack.enter_context(patch.object(macbridge.time, "monotonic",
                                                         side_effect=[0, 0, macbridge.READ_TIMEOUT]))
                result = macbridge.transfer(ident, str(source), [], io.StringIO())
                self.assertIs(result, False)
                call.assert_called_once()
                argv = call.call_args.args[0]
                self.assertEqual(argv[:3], ["ssh", "-T", "myserver"])
                self.assertIn(shlex.quote(reason), argv[-1])
                self.assertIn(f"/.{ident}.error.part && mv -f ", argv[-1])
                self.assertTrue(argv[-1].endswith(f"/.{ident}.error"))
                self.assertFalse(stale.exists())
                self.assertEqual(list((root / "reads").iterdir()), [])
                self.assertEqual(list((root / "staged").iterdir()), [])
                self.assertEqual(sleep.call_count, int(live))
                self.assertEqual(clock.call_count, 3 if live else 0)

    def test_error_marker_is_atomic_one_line_and_shell_quoted(self):
        root = macbridge.directories()
        ident = "0123456789abcdef"
        text = "can't send $(touch escaped); `touch escaped2`\nscp failed"
        with patch.object(macbridge.subprocess, "run") as call:
            macbridge.publish_error(ident, text, [], io.StringIO())
        command = call.call_args.args[0][-1]
        self.assertEqual(call.call_args.args[0][:3], ["ssh", "-T", "myserver"])
        result = subprocess.run(["sh", "-c", command], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = root / "inbox" / f".{ident}.error"
        self.assertEqual(marker.read_text(), " ".join(text.splitlines()) + "\n")
        self.assertEqual(list((root / "inbox").iterdir()), [marker])
        self.assertFalse((self.root / "escaped").exists())
        self.assertFalse((self.root / "escaped2").exists())

    def test_singleton_lock_releases_and_background_inherits_ownership(self):
        inherited = []

        def spawn(*args, **kwargs):
            inherited.append(os.dup(kwargs["pass_fds"][0]))
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(args[0][2], "macbridge")
            self.assertIn(args[0][3], ("--reader", "--lock-fd"))
        with patch.object(macbridge.sys, "platform", "darwin"), \
                patch.object(macbridge, "terminal_app_pid", return_value=300), \
                patch.object(macbridge.subprocess, "Popen", side_effect=spawn) as call:
            try:
                macbridge.start_background()
                macbridge.start_background()
                self.assertEqual(call.call_count, 2)
                self.assertEqual({args.args[0][3] for args in call.call_args_list},
                                 {"--reader", "--lock-fd"})
            finally:
                for fd in inherited:
                    os.close(fd)
        with macbridge.acquire_lock():
            self.assertIsNone(macbridge.acquire_lock())

    def test_background_starts_reader_even_when_bridge_already_runs(self):
        with macbridge.acquire_lock(), \
                patch.object(macbridge.sys, "platform", "darwin"), \
                patch.object(macbridge, "start_reader") as reader, \
                patch.object(macbridge.subprocess, "Popen") as spawn:
            macbridge.start_background()
        reader.assert_called_once()
        spawn.assert_not_called()

    def test_non_mac_guard_and_menu_autostart_skips_dry_run(self):
        with patch.object(macbridge.sys, "platform", "linux"), \
                patch.object(macbridge.subprocess, "Popen") as spawn:
            macbridge.start_background()
            with self.assertRaisesRegex(config.Error, "macOS"):
                macbridge.main([])
            spawn.assert_not_called()
        with patch.object(macbridge, "start_background") as start, \
                patch.object(config, "server_alias", return_value="myserver"), \
                patch.object(menu, "client", return_value=0):
            menu.main(["--dry-run"])
            start.assert_not_called()
            menu.main([])
            start.assert_called_once()

    def test_reconnect_backoff_and_retry_consumed_request(self):
        stream = Mock()
        stream.stdout = io.StringIO("0123456789abcdef\t/Users/me/logo.png\n")
        stream.stdin = self.stack.enter_context(tempfile.TemporaryFile(dir=self.root))
        stream.poll.return_value = 0
        log = io.StringIO()
        with patch.object(macbridge.subprocess, "Popen", side_effect=[OSError("offline"), OSError("offline"), stream]), \
                patch.object(macbridge, "transfer", side_effect=[OSError("dropped"), None]) as transfer, \
                patch.object(macbridge.time, "sleep", side_effect=[None, None, None, KeyboardInterrupt]) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                macbridge.bridge_loop(self.root, log)
        self.assertEqual(transfer.call_count, 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 1, 1])
        self.assertIn("transfer 0123456789abcdef failed", log.getvalue())
        self.assertTrue(stream.stdin.closed)

    def test_failed_transfer_does_not_starve_the_next_request(self):
        stream = Mock()
        stream.stdout = io.StringIO("0123456789abcdef\t/Users/me/bad.png\n"
                                    "1123456789abcdef\t/Users/me/good.png\n")
        stream.stdin = self.stack.enter_context(tempfile.TemporaryFile(dir=self.root))
        stream.poll.return_value = 0
        log = io.StringIO()
        with patch.object(macbridge.subprocess, "Popen", return_value=stream), \
                patch.object(macbridge.subprocess, "run", side_effect=OSError("offline")) as publish, \
                patch.object(macbridge, "transfer", side_effect=[OSError("denied")] * 3 + [None]) as transfer, \
                patch.object(macbridge.time, "sleep", side_effect=[None, None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                macbridge.bridge_loop(self.root, log)
        self.assertEqual(transfer.call_args.args[0], "1123456789abcdef")
        self.assertIn("transfer 0123456789abcdef abandoned", log.getvalue())
        publish.assert_called_once()
        self.assertIn("denied", publish.call_args.args[0][-1])
        self.assertTrue(publish.call_args.args[0][-1].endswith("/.0123456789abcdef.error"))
        self.assertIn("error marker 0123456789abcdef failed: offline", log.getvalue())

    def test_permission_failure_is_an_outcome_without_retries_or_false_delivery_log(self):
        source = self.root / "dropped.png"
        source.touch()
        stream = Mock()
        stream.stdout = io.StringIO(f"0123456789abcdef\t{source}\n")
        stream.stdin = self.stack.enter_context(tempfile.TemporaryFile(dir=self.root))
        stream.poll.return_value = 0
        log = io.StringIO()
        with patch.object(macbridge.subprocess, "Popen", return_value=stream), \
                patch.object(macbridge.subprocess, "run") as publish, \
                patch("builtins.open", side_effect=PermissionError), \
                patch.object(macbridge.time, "sleep", side_effect=KeyboardInterrupt) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                macbridge.bridge_loop(self.root, log)
        publish.assert_called_once()
        self.assertIn(macbridge.READ_ERROR, publish.call_args.args[0][-1])
        sleep.assert_called_once_with(1)  # Reconnect, not a transfer retry.
        self.assertIn(macbridge.READ_ERROR, log.getvalue())
        self.assertNotIn("delivered", log.getvalue())


class Install(Sandbox):
    def test_launch_agent_is_well_formed_loaded_and_idempotent(self):
        with patch.object(macbridge.subprocess, "run", return_value=Mock(returncode=1)) as call, \
                redirect_stdout(io.StringIO()):
            macbridge.install_launch_agent()
        path = self.root / "Library/LaunchAgents/com.agentkit.macbridge.plist"
        data = plistlib.loads(path.read_bytes())
        self.assertTrue(data["KeepAlive"])
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["ProgramArguments"], [sys.executable,
                         str(self.root / ".local/bin/ak"), "macbridge"])
        self.assertEqual(call.call_args.args[0], ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)])
        stamp = path.stat().st_mtime_ns
        with patch.object(macbridge.subprocess, "run", return_value=Mock(returncode=0)) as call, \
                redirect_stdout(io.StringIO()):
            macbridge.install_launch_agent()
            self.assertEqual(call.call_count, 2)
            self.assertEqual(call.call_args.args[0], ["launchctl", "kickstart", "-k",
                                                    f"gui/{os.getuid()}/{macbridge.LABEL}"])
        self.assertEqual(path.stat().st_mtime_ns, stamp)
        if shutil.which("plutil"):
            result = subprocess.run(["plutil", "-lint", "--", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_launch_agent_sandbox_never_calls_launchctl(self):
        with patch.object(macbridge.subprocess, "run") as call, redirect_stdout(io.StringIO()):
            macbridge.install_launch_agent(load=False)
            macbridge.install_launch_agent(load=False)
        call.assert_not_called()

    def test_installer_skips_bridge_on_linux_and_writes_plist_on_mac(self):
        fakebin = self.root / "bin"
        fakebin.mkdir()
        # No real tmux server, browser, launchctl or package manager can be reached.
        for name in ("tmux", "launchctl"):
            path = fakebin / name
            path.write_text("#!/bin/sh\nexit 1\n")
            path.chmod(0o700)
        for system in ("Linux", "Darwin", "Darwin"):
            uname = fakebin / "uname"
            uname.write_text(f"#!/bin/sh\necho {system}\n")
            uname.chmod(0o700)
            with patch.dict(os.environ, {"PATH": f"{fakebin}:{os.environ['PATH']}"}):
                result = subprocess.run(["bash", str(REPO / "install.sh"), "--client", "myserver"],
                                        capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plist = self.root / "Library/LaunchAgents/com.agentkit.macbridge.plist"
            if system == "Linux":
                self.assertFalse(plist.exists())
                self.assertFalse(self.bridge.exists())
                self.assertFalse((self.root / ".zshrc").exists())
                self.assertNotIn("ak macbridge --reader", (self.root / ".bashrc").read_text())
            else:
                self.assertEqual(plistlib.loads(plist.read_bytes())["Label"], macbridge.LABEL)
                self.assertIn("sandbox: launchctl skipped", result.stdout)
                rc = (self.root / ".zshrc").read_text()
                line = ("[[ -o interactive ]] && command -v ak >/dev/null 2>&1 && "
                        "{ ak macbridge --reader >/dev/null 2>&1 &! }")
                self.assertEqual(rc.count(line), 1)
                self.assertLess(rc.index("# agentkit aliases"), rc.index(line))
                self.assertLess(rc.index(line), rc.index("# end agentkit aliases"))


if __name__ == "__main__":
    unittest.main()
