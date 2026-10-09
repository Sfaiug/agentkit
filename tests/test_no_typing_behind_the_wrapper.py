"""A drained pane does not invite typing while the wrapped harness has unread input.

Real outer and inner PTYs, the real wrapper and relay, and a fake tmux: no server or model.
"""
import fcntl
import json
import os
import select
import struct
import subprocess
import sys
import termios
import time
import tty
import unittest
from unittest.mock import Mock, patch

from fixtures.seats import LINE, NOW, REPO, SEAT, Seats
from agentkit import config, orch, statusbar, watch
from agentkit.pty_relay import Relay

TMUX = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['FAKE_TMUX_ROOT'])
state = root / 'tmux.json'
given = json.loads(state.read_text())
args = sys.argv[1:]
if args[0] in ('-S', '-L'):
    flag, server, *args = args
    assert server == (str(root / 'server') if flag == '-S' else given['socket'])
else:
    assert given['socket'] == ''
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps(args) + '\n')
commands = [[]]
for arg in args:
    if arg == ';':
        commands.append([])
    else:
        commands[-1].append(arg)
changed = False
for args in commands:
    target = args[args.index('-t') + 1]
    if args[0] == 'display-message':
        assert args[:3] == ['display-message', '-p', '-t']
        owner = given['name'] if target in ('%7', '=' + given['name'] + ':') else 'acme-other'
        print(args[4].replace('#{pane_tty}', given['outer']).replace(
            '#{@ak_input_tty}', given['options'].get('@ak_input_tty', '')).replace(
            '#{session_name}', owner))
    else:
        assert target in ('%7', '=' + given['name'] + ':')
        if args[0] == 'set-option':
            if args[4] == '@ak_input_tty':
                assert args[1] in ('-p', '-pu')
                if args[1] == '-pu':
                    given['options'].pop(args[4], None)
                else:
                    given['options'][args[4]] = args[5]
            else:
                assert args[1] == '-F' and args[4:] == ['@ak_harness_pane', '#{pane_id}']
                given['bound'] = '%7'
            changed = True
        elif args[0] == 'show-options':
            assert args[-1] == '@ak_harness_pane'
            print(given.get('bound', '%7'))
        elif args[0] == 'respawn-pane':
            if given.get('refuse_respawn'):
                sys.exit(1)
            given['respawned'] = True
            changed = True
        else:
            assert args[0] == 'set-environment'
if changed:
    temp = state.with_suffix('.tmp')
    temp.write_text(json.dumps(given))
    temp.replace(state)
'''

HARNESS = r'''
import json, os, time, tty
from pathlib import Path
root = Path(os.environ['FAKE_TMUX_ROOT'])
tty.setraw(0)
(root / 'ready.tmp').write_text(json.dumps({'tty': os.ttyname(0),
    'named': json.loads((root / 'tmux.json').read_text())['options'].get('@ak_input_tty')}))
(root / 'ready.tmp').replace(root / 'ready')
while not (root / 'read').exists():
    time.sleep(.01)
with (root / 'received').open('ab', buffering=0) as received:
    while True:
        data = os.read(0, 65536)
        if not data:
            break
        received.write(data)
'''


def unread(fd):
    return struct.unpack('i', fcntl.ioctl(fd, termios.FIONREAD, struct.pack('i', 0)))[0]


class WrappedPane(Seats):
    def setUp(self):
        self.client = orch.tmux_out
        super().setUp()
        self.master, self.slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        tty.setraw(self.slave)
        fake_bin = self.root / 'bin'
        fake_bin.mkdir()
        (fake_bin / 'tmux').write_text(TMUX)
        (fake_bin / 'tmux').chmod(0o755)
        self.state = self.root / 'tmux.json'
        self.state.write_text(json.dumps({'outer': os.ttyname(self.slave), 'name': SEAT,
                                         'socket': 'acme-test', 'options': {}}))
        environment = patch.dict(os.environ, {
            'PATH': str(fake_bin) + os.pathsep + os.environ['PATH'],
            'FAKE_TMUX_ROOT': str(self.root), 'AGENTKIT_TMUX_SOCKET': 'acme-test'})
        environment.start()
        self.addCleanup(environment.stop)
        self.start_wrapper()

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready():
            self.assertIsNone(self.proc.poll(), 'wrapper exited before the expected input')
            self.assertLess(time.monotonic(), deadline, 'terminal did not reach the expected state')
            select.select([], [], [], .01)

    def start_wrapper(self):
        (self.root / 'ready').unlink(missing_ok=True)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('AGENTKIT_', 'AK_', 'IDLE_COMPACT_'))
               and key not in ('TMUX', 'TMUX_PANE')}
        env.update(HOME=str(self.root), AGENTKIT_SESSION=SEAT,
                   AGENTKIT_TMUX_SOCKET='a-different-server',
                   TMUX=f'{self.root / "server"},123,0', TMUX_PANE='%7')
        self.proc = subprocess.Popen([sys.executable, str(REPO / 'tools/idle-compact.py'),
                                      '--poll', '.01', '--', sys.executable, '-c', HARNESS],
                                     stdin=self.slave, stdout=self.slave, stderr=subprocess.PIPE,
                                     cwd=self.root, env=env)
        self.addCleanup(self.stop, self.proc)
        self.until(lambda: (self.root / 'ready').exists())
        self.ready = json.loads((self.root / 'ready').read_text())
        self.inner = os.open(self.ready['tty'], os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
        self.inner_reader = os.fdopen(self.inner, 'rb', buffering=0)
        self.addCleanup(self.inner_reader.close)

    def respawn(self, client=None):
        with patch.object(orch, 'tmux_out', client or self.client), \
                patch.object(orch, 'user_manager', return_value=False), \
                patch.object(orch.guard, 'install_shim', return_value=self.root / 'bin'), \
                patch.object(statusbar, 'dress'):
            orch._start_harness(SEAT, 'gemini', self.root, ['true'], self.seat)

    def stop(self, proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        proc.wait(timeout=10)
        proc.stderr.close()

    def tmux(self, *args, **kwargs):
        if args[0] == 'display-message':
            self.assertEqual(kwargs.get('socket'), orch.seat_socket(self.seat))
            self.assertIsNotNone(kwargs.get('timeout'))
            return self.client(*args, **kwargs)
        self.assertEqual(os.write(self.master, args[-1].encode() if '-l' in args else b'\r'),
                         len(args[-1].encode()) if '-l' in args else 1)
        return super().tmux(*args, **kwargs)

    def held_input(self):
        data = b'd' * 1398
        self.assertEqual(os.write(self.master, data), len(data))
        self.until(lambda: unread(self.slave) == 0 and unread(self.inner) == len(data))
        return data

    def release_reader(self, expected):
        (self.root / 'read').touch()
        received = self.root / 'received'
        self.until(lambda: received.exists() and received.read_bytes() == expected)
        self.until(lambda: unread(self.slave) == unread(self.inner) == 0)

    def test_the_wrapper_names_its_tty_before_exec_once_per_start_replacing_the_previous_name(self):
        for start in range(2):
            if start:
                self.start_wrapper()
            self.assertEqual(self.ready['named'], self.ready['tty'])
            self.assertNotEqual(self.ready['tty'], os.ttyname(self.slave))
            for _ in range(3):
                self.assertFalse(watch.pane_unread(self.seat))
            calls = [json.loads(line) for line in (self.root / 'calls.jsonl').read_text().splitlines()]
            self.assertEqual(sum(call[:2] == ['set-option', '-p'] for call in calls), start + 1)
            self.stop(self.proc)

    def test_the_empty_outer_tty_does_not_release_an_ak_line_until_the_harness_reads(self):
        data = self.held_input()
        self.wait_line()
        for _ in range(3):
            self.tick()
        self.assertEqual(self.typed, [])
        self.assertFalse(self.told())
        self.assertEqual(self.receipts(), [])
        sent, typed = Mock(return_value=(0, '')), Mock()
        self.assertIsNone(watch._send_line(self.seat, '/compact', lambda _: None, typed, send=sent))
        sent.assert_not_called()
        typed.assert_not_called()
        self.release_reader(data)
        for _ in range(3):
            self.tick()
        line = LINE
        self.assertEqual(self.typed, [line])
        self.assertTrue(self.told())
        self.assertEqual(len(self.receipts()), 1)
        self.until(lambda: (self.root / 'received').read_bytes() == data + line.encode() + b'\r')

    def test_renaming_and_a_legacy_server_keep_the_fact_on_the_same_pane(self):
        self.held_input()
        given = json.loads(self.state.read_text())
        given.update(name='acme-renamed', socket='')
        self.state.write_text(json.dumps(given))
        self.seat.update(name='acme-renamed', legacy=True)
        self.assertTrue(watch.pane_unread(self.seat))

    def test_recovery_notices_spend_no_tries_while_the_inner_tty_is_unread(self):
        self.held_input()
        for accounts in (False, True):
            with self.subTest(accounts=accounts):
                mark = {'boot': watch.boot_id(), 'at': NOW - 100, 'name': SEAT,
                        'tries': watch.MIDTURN_TRIES - 1}
                if accounts:
                    mark['line'] = watch.ACCOUNT_LINE
                watch.seat_write(SEAT, midturn=mark)
                for _ in range(watch.MIDTURN_TRIES + 1):
                    watch.continue_turns(self.cfg, lambda _: None, accounts=accounts)
                self.assertEqual(watch.seat_read(SEAT).get('midturn'), mark)
        self.assertEqual(self.typed, [])
        self.assertEqual(self.receipts(), [])

    def test_an_unwrapped_respawn_forgets_a_recycled_inner_tty(self):
        self.stop(self.proc)
        self.inner_reader.close()
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        tty.setraw(slave)
        os.write(master, b'other seat unread draft')
        self.assertEqual(select.select([slave], [], [], 5)[0], [slave])
        for bound, legacy in (('%7', False), ('', True), ('%8', False)):
            with self.subTest(bound=bound, legacy=legacy):
                given = json.loads(self.state.read_text())
                # Model reuse explicitly: the host can allocate PTYs between these opens.
                given['options']['@ak_input_tty'] = os.ttyname(slave)
                given.update(bound=bound, socket='' if legacy else 'acme-test')
                self.state.write_text(json.dumps(given))
                self.seat['legacy'] = legacy
                self.assertTrue(watch.pane_unread(self.seat))
                self.respawn()
                self.assertTrue(json.loads(self.state.read_text())['respawned'])
                self.assertEqual(unread(self.slave), 0)
                self.assertGreater(unread(slave), 0)
                self.assertFalse(watch.pane_unread(self.seat))
                sent = Mock(return_value=(0, ''))
                self.assertTrue(watch._send_line(self.seat, 'Run finished.', lambda _: None, send=sent))
                sent.assert_called_once_with('Run finished.')

    def test_a_refused_respawn_keeps_the_live_wrappers_guard(self):
        self.held_input()
        given = json.loads(self.state.read_text())
        before = dict(given['options'])
        given['refuse_respawn'] = True
        self.state.write_text(json.dumps(given))
        with self.assertRaises(config.Error):
            self.respawn()
        self.assertIsNone(self.proc.poll())
        self.assertEqual(json.loads(self.state.read_text())['options'], before)
        self.assertTrue(watch.pane_unread(self.seat))

    def test_respawn_clears_the_old_name_before_a_new_wrapper_can_publish(self):
        self.stop(self.proc)

        def client(*args, **kwargs):
            answer = self.client(*args, **kwargs)
            if args[0] == 'respawn-pane' and answer[0] == 0:
                self.start_wrapper()
            return answer

        self.respawn(client)
        self.assertEqual(json.loads(self.state.read_text())['options']['@ak_input_tty'],
                         self.ready['tty'])
        self.held_input()
        self.assertTrue(watch.pane_unread(self.seat))
        calls = [json.loads(line) for line in (self.root / 'calls.jsonl').read_text().splitlines()]
        respawn = next(call for call in calls if call[0] == 'respawn-pane')
        self.assertEqual(respawn[respawn.index(';') + 1:],
                         ['set-option', '-pu', '-t', '%7', '@ak_input_tty'])


class RelayBacklog(Seats):
    def setUp(self):
        super().setUp()
        self.outer_master, self.outer_slave = os.openpty()
        self.inner_master, self.inner_slave = os.openpty()
        for fd in (self.outer_master, self.outer_slave, self.inner_master, self.inner_slave):
            self.addCleanup(os.close, fd)
        for fd in (self.outer_slave, self.inner_slave):
            tty.setraw(fd)
            os.set_blocking(fd, False)
        os.set_blocking(self.outer_master, False)
        self.paths = [os.ttyname(self.outer_slave), os.ttyname(self.inner_slave)]
        self.relay = Relay(self.inner_master, self.outer_slave, self.outer_slave, lambda _: None)
        self.addCleanup(self.relay.close)

    def tmux(self, *args, **kwargs):
        self.assertEqual(args[0], 'display-message')
        self.assertEqual(args[args.index('-t') + 1], f'={SEAT}:')
        return 0, args[-1].replace('#{pane_tty}', self.paths[0]).replace(
            '#{@ak_input_tty}', self.paths[1])

    def test_each_terminal_can_hold_a_line_even_when_the_other_is_empty_or_unavailable(self):
        sent = Mock(return_value=(0, ''))
        for master, slave, other in ((self.outer_master, self.outer_slave, 1),
                                     (self.inner_master, self.inner_slave, 0)):
            os.write(master, b'draft')
            self.assertEqual(select.select([slave], [], [], 5)[0], [slave])
            original = self.paths[other]
            for path in (original, str(self.root / 'missing-tty')):
                self.paths[other] = path
                self.assertIsNone(watch._send_line(self.seat, 'Run finished.', lambda _: None, send=sent))
                self.assertEqual(unread(slave), 5)
            self.paths[other] = original
            self.assertEqual(os.read(slave, 5), b'draft')
        sent.assert_not_called()
        self.assertEqual(self.receipts(), [])

    def test_a_reader_that_never_reads_leaves_the_inner_tty_full_when_the_relay_queues_input(self):
        # Keep both real tty readers open, without taking a byte from either.
        for _ in range(200):
            try:
                os.write(self.outer_master, b'd' * 16384)
            except BlockingIOError:
                pass
            self.relay.poll(.01)
            if self.relay.to_child and not select.select([], [self.inner_master], [], 0)[1]:
                break
        else:
            self.fail('the non-reading harness did not back up its terminal')
        for _ in range(200):
            self.relay.poll(.01)
            if unread(self.outer_slave) == 0:
                break
        self.assertEqual(unread(self.outer_slave), 0)
        self.assertTrue(self.relay.to_child)
        self.assertGreater(unread(self.inner_slave), 0)
        queued = bytes(self.relay.to_child)
        self.relay.poll(0)
        self.assertEqual(bytes(self.relay.to_child), queued)
        sent = Mock(return_value=(0, ''))
        self.assertIsNone(watch._send_line(self.seat, 'Run finished.', lambda _: None, send=sent))
        sent.assert_not_called()
        self.assertEqual(self.receipts(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
