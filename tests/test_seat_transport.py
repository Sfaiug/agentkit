"""A wrapped terminal makes progress when its two directions fill together.

Real PTYs and pipes, a fake harness, and an isolated HOME; no model or live seat.
"""
import errno
import hashlib
import json
import fcntl
import pty
import signal
import struct
import termios
import tty
from unittest.mock import patch
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / 'tools/idle-compact.py'
sys.path.insert(0, str(REPO))

HARNESS = r'''
import hashlib, json, os, sys, time, tty
from pathlib import Path
tty.setraw(0)
root = Path(sys.argv[1])
(root / 'ready').touch()
while not (root / 'go').exists():
    time.sleep(.01)
output = bytes(range(256)) * 4096
view = memoryview(output)
while view:
    view = view[os.write(1, view):]
received = bytearray()
while len(received) < int(sys.argv[2]):
    received.extend(os.read(0, 65536))
(root / 'received').write_text(hashlib.sha256(received).hexdigest())
sys.exit(7)
'''


class SeatTransport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='.ak-test-transport-', dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('AGENTKIT_', 'AK_', 'IDLE_COMPACT_'))}
        self.env.update(HOME=str(self.root), XDG_DATA_HOME=str(self.root / 'share'))

    def stop(self, proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream:
                stream.close()

    def test_simultaneous_input_and_redraw_pressure_preserves_every_byte(self):
        fake = self.root / 'harness.py'
        fake.write_text(HARNESS)
        data = b'\x1b[<35;12;6M' * 32768 + b'an owner draft\x1b'
        proc = subprocess.Popen([sys.executable, str(WRAPPER), '--poll', '.05', '--',
                                 sys.executable, str(fake), str(self.root), str(len(data))],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=self.env, cwd=self.root)
        self.addCleanup(self.stop, proc)
        deadline = time.monotonic() + 20
        while not (self.root / 'ready').exists():
            self.assertIsNone(proc.poll(), 'the fake harness did not start')
            self.assertLess(time.monotonic(), deadline, 'the fake harness did not become ready')
            time.sleep(.01)
        os.set_blocking(proc.stdin.fileno(), False)
        os.set_blocking(proc.stdout.fileno(), False)
        pending = memoryview(data)
        # No output has been written yet and the harness reads no input. Fill the
        # input pipe before releasing the harness to redraw ahead of reading it.
        while pending:
            try:
                pending = pending[os.write(proc.stdin.fileno(), pending):]
            except BlockingIOError:
                break
        (self.root / 'go').touch()
        output = bytearray()
        eof = False
        while not eof and time.monotonic() < deadline:
            reads, writes, _ = select.select([proc.stdout], [proc.stdin] if pending else [], [], .05)
            if proc.stdout in reads:
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    eof = True
                output.extend(chunk)
            if proc.stdin in writes:
                try:
                    pending = pending[os.write(proc.stdin.fileno(), pending):]
                except (BlockingIOError, BrokenPipeError):
                    pass
        self.assertTrue(eof, 'terminal deadlocked with input and redraw output pending')
        self.assertFalse(pending, 'input was lost')
        self.assertEqual(proc.wait(timeout=5), 7, proc.stderr.read().decode())
        self.assertEqual(bytes(output), bytes(range(256)) * 4096)
        self.assertEqual((self.root / 'received').read_text(), hashlib.sha256(data).hexdigest())

    def test_a_backed_up_display_never_compacts_from_its_stale_prompt(self):
        from agentkit.pty_relay import BUFFER_LIMIT
        adapters = self.root / 'adapters'
        adapters.mkdir()
        (adapters / 'plain.toml').write_text('''version = 1
[compact]
command = ["/compact", "\\r"]
signal = "screen"
context = "muse-session"
idle = 30
stash = "none"
[screen]
composer = ">$"
[[rule]]
state = "at_prompt"
at_composer = true
lines = 8
none = ["esc to interrupt"]
''')
        fake = self.root / 'busy.py'
        fake.write_text(r'''
import json, os, select, sys, time, tty
from pathlib import Path
tty.setraw(0)
root = Path(os.environ["HOME"])
directory = Path(os.environ["XDG_DATA_HOME"]) / "muse/sessions/2026/10/08/fake"
directory.mkdir(parents=True)
(directory / "session.jsonl").write_text(json.dumps({"payload": {
 "kind": "route_facts", "record": {"pid": os.getpid()}}}) + "\n" + json.dumps({"payload": {
 "event": {"kind": "goal_usage_attribution", "record": {"usage_family": "provider",
 "owner": {"owner_type": "main_root"}, "quantity": {"input_tokens": 40000}}}}}) + "\n")
view = memoryview(b">" * int(sys.argv[1]))
while view:
 view = view[os.write(1, view):]
os.write(1, b"\nesc to interrupt\n>\n")
received = bytearray()
until = time.monotonic() + 2
while time.monotonic() < until:
 if select.select([0], [], [], .05)[0]:
  received.extend(os.read(0, 65536))
(root / "received").write_bytes(received)
''')
        reader, writer = os.pipe()
        self.addCleanup(os.close, reader)
        capacity = fcntl.fcntl(writer, fcntl.F_GETPIPE_SZ)
        proc = subprocess.Popen([sys.executable, str(WRAPPER), '--harness', 'plain',
                                 '--idle', '.05', '--poll', '.01', '--',
                                 sys.executable, str(fake), str(capacity + BUFFER_LIMIT)],
                                stdin=subprocess.PIPE, stdout=writer, stderr=subprocess.PIPE,
                                cwd=self.root, env={**self.env, 'AGENTKIT_ADAPTER_DIR': str(adapters)})
        os.close(writer)
        self.addCleanup(self.stop, proc)
        received = self.root / 'received'
        deadline = time.monotonic() + 20
        while not received.exists() and time.monotonic() < deadline:
            self.assertIsNone(proc.poll(), 'fake harness exited before recording input')
            time.sleep(.01)
        self.assertTrue(received.exists(), 'fake harness could not write its busy marker')
        os.set_blocking(reader, False)
        while proc.poll() is None and time.monotonic() < deadline:
            if select.select([reader], [], [], .05)[0]:
                os.read(reader, 65536)
        self.assertEqual(proc.wait(timeout=5), 0, proc.stderr.read().decode())
        self.assertEqual(received.read_bytes(), b'', 'an unread busy marker must defer compaction')


class RelayIO(unittest.TestCase):
    def setUp(self):
        from agentkit.pty_relay import Relay
        self.master, self.slave = pty.openpty()
        self.source, self.owner = os.pipe()
        self.screen, self.sink = os.pipe()
        self.fds = [self.master, self.slave, self.source, self.owner, self.screen, self.sink]
        self.addCleanup(self.close)
        tty.setraw(self.slave)
        os.set_blocking(self.slave, False)
        os.set_blocking(self.screen, False)
        self.seen = bytearray()
        self.relay = Relay(self.master, self.source, self.sink, self.seen.extend)

    def close(self):
        if self.relay is not None:
            self.relay.close()
        for fd in self.fds:
            os.close(fd)

    def close_fd(self, fd):
        os.close(fd)
        self.fds.remove(fd)

    def read(self, fd):
        try:
            return os.read(fd, 65536)
        except BlockingIOError:
            return b''

    def test_one_poll_delivers_new_input_to_the_harness(self):
        from agentkit.pty_relay import Relay
        outer_master, outer_slave = pty.openpty()
        self.fds.extend((outer_master, outer_slave))
        tty.setraw(outer_slave)
        self.relay.close()
        self.relay = Relay(self.master, outer_slave, outer_slave, self.seen.extend)
        original = os.write
        draft = b'unread owner draft'
        for short in (False, True):
            with self.subTest(short_writes=short):
                interrupted = False

                def write(fd, data):
                    nonlocal interrupted
                    if short and fd == self.master:
                        if not interrupted:
                            interrupted = True
                            raise InterruptedError()
                        data = data[:3]
                    return original(fd, data)

                os.write(outer_master, draft)
                self.assertTrue(select.select([outer_slave], [], [], 5)[0])
                with patch('agentkit.pty_relay.os.write', side_effect=write):
                    self.relay.poll(0)
                # Do not poll the relay again: a delayed wrapper must leave the
                # draft in the harness's terminal, where the typing guard sees it.
                self.assertTrue(select.select([self.slave], [], [], 5)[0],
                                'input waited in the relay for a second poll')
                self.assertEqual(self.read(self.slave), draft)

    def test_short_writes_and_retries_keep_both_streams_in_order(self):
        incoming = b'owner draft\x1b[<35;12;6M\x1b' * 20
        outgoing = bytes(range(256)) * 3
        os.write(self.owner, incoming)
        os.write(self.slave, outgoing)
        original = os.write
        calls = {self.master: 0, self.sink: 0}

        def short(fd, data):
            if fd in calls:
                calls[fd] += 1
                if calls[fd] == 1:
                    raise BlockingIOError(errno.EAGAIN, 'not ready after all')
                if calls[fd] == 2:
                    raise InterruptedError()
                return original(fd, data[:3])
            return original(fd, data)

        received, displayed = bytearray(), bytearray()
        with patch('agentkit.pty_relay.os.write', side_effect=short):
            for _ in range(len(incoming) + len(outgoing)):
                self.relay.poll(0)
                received.extend(self.read(self.slave))
                displayed.extend(self.read(self.screen))
                if received == incoming and displayed == outgoing:
                    break
        self.assertEqual(received, incoming)
        self.assertEqual(displayed, outgoing)
        self.assertEqual(self.seen, outgoing)

    def test_a_slow_display_bounds_memory_and_still_delivers_input(self):
        from agentkit.pty_relay import BUFFER_LIMIT
        block = bytes(range(256)) * 256
        sent = 0
        for _ in range(100):
            try:
                sent += os.write(self.slave, block)
            except BlockingIOError:
                pass
            self.relay.poll(0)
            self.assertLessEqual(len(self.relay.to_owner), BUFFER_LIMIT)
            self.assertLessEqual(len(self.relay.to_child), BUFFER_LIMIT)
        self.assertEqual(len(self.relay.to_owner), BUFFER_LIMIT)
        os.write(self.owner, b'escape\x1b')
        received = bytearray()
        for _ in range(100):
            self.relay.poll(0)
            received.extend(self.read(self.slave))
            if received == b'escape\x1b':
                break
        self.assertEqual(received, b'escape\x1b')
        displayed = bytearray()
        for _ in range(1000):
            displayed.extend(self.read(self.screen))
            self.relay.poll(0)
            if len(displayed) == sent:
                break
        self.assertEqual(len(displayed), sent)
        self.assertEqual(displayed, self.seen)

    def test_stdin_eof_is_ordered_after_the_last_input(self):
        os.write(self.owner, b'last input')
        self.close_fd(self.owner)
        received = bytearray()
        for _ in range(20):
            self.relay.poll(0)
            received.extend(self.read(self.slave))
        self.assertEqual(received, b'last input\x04')
        self.assertFalse(self.relay.input_open)

    def test_injected_keys_drain_redraws(self):
        from agentkit.pty_relay import Relay
        # A fake child writes more than the transport's buffer before it reads
        # the injected command, exactly the cycle normal typing used to hit.
        code = """import os, termios, tty
from pathlib import Path
tty.setraw(0, termios.TCSANOW)
view = memoryview(b'R' * 262144)
while view:
 view = view[os.write(1, view):]
received = b''
while len(received) < 131073:
 received += os.read(0, 65536)
Path(os.environ['RECEIPT']).write_bytes(received)
"""
        with tempfile.TemporaryDirectory(prefix='.ak-test-inject-', dir=REPO) as root:
            receipt = Path(root) / 'received'
            os.set_blocking(self.slave, True)
            child = subprocess.Popen([sys.executable, '-c', code], stdin=self.slave,
                                     stdout=self.slave, env={**os.environ, 'RECEIPT': str(receipt)})
            def reap():
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
            self.addCleanup(reap)
            # A regular file is an unblocked terminal sink, without a second
            # thread or another reader in this test's process.
            with (Path(root) / 'screen').open('wb') as screen:
                self.relay.close()
                self.relay = Relay(self.master, self.source, screen.fileno(), self.seen.extend,
                                   lambda: child.poll() is None)
                try:
                    self.assertTrue(self.relay.send([b'K' * 131072, b'\r'], .01))
                    self.assertEqual(child.wait(timeout=10), 0)
                    self.relay.finish()
                finally:
                    self.relay.close()
                    self.relay = None
            self.assertEqual(receipt.read_bytes(), b'K' * 131072 + b'\r')
            self.assertEqual((Path(root) / 'screen').read_bytes(), b'R' * 262144)

    def test_closing_the_child_retains_its_final_output(self):
        os.write(self.slave, b'last screen')
        self.close_fd(self.slave)
        for _ in range(20):
            self.relay.poll(0)
        self.assertFalse(self.relay.active)
        self.assertEqual(self.read(self.screen), b'last screen')

    def test_close_restores_descriptor_flags(self):
        self.assertFalse(os.get_blocking(self.master))
        self.assertFalse(os.get_blocking(self.source))
        self.assertFalse(os.get_blocking(self.sink))
        self.relay.close()
        self.assertTrue(os.get_blocking(self.master))
        self.assertTrue(os.get_blocking(self.source))
        self.assertTrue(os.get_blocking(self.sink))


if __name__ == '__main__':
    unittest.main(verbosity=2)
