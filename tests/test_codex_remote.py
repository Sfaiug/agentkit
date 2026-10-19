"""Per-seat app servers, lifecycle and pairing. All processes and homes are fakes."""
from contextlib import ExitStack
import json
import os
import runpy
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify
from agentkit.harness import codex

FAKE = (REPO / 'tests/fixtures/codex-remote-fake.py').read_text()


class Remote(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='.remote-')))
        (self.root / 'sitecustomize.py').write_text(
            (REPO / 'tests/fixtures/codex-remote-http-fake.py').read_text())
        self.stack.enter_context(patch.dict(os.environ, {'PYTHONPATH': str(self.root)}))
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.fake('codex', FAKE)
        self.fake('tmux', '''import json, os, pathlib, signal, sys
root = pathlib.Path.home()
assert sys.argv[1:3] == ['-L', 'agentkit-test'], sys.argv
if 'kill-session' in sys.argv:
    assert sys.argv[-1].startswith('=acme-') and sys.argv[-1].endswith(':')
    name = sys.argv[-1][1:-1]
    os.kill(int((root / ('seat-pid-' + name)).read_text()), signal.SIGTERM)
''')
        self.stack.enter_context(patch.dict(os.environ, {
            'HOME': str(self.root), 'CODEX_HOME': str(self.root / '.codex'),
            'TMPDIR': str(self.root), 'PATH': f'{self.bin}:{os.environ["PATH"]}',
            'FAKE_CODEX_REPO': str(REPO), 'FAKE_THREAD': 'acme-thread', 'FAKE_HOLD': '1',
            'AGENTKIT_SESSION': 'acme-seat', 'AGENTKIT_TMUX_SOCKET': 'agentkit-test',
            'AK_NOTIFY_SINK': str(self.root / 'notices'), 'AGENTKIT_DISCORD_WEBHOOK': 'off',
            'AGENTKIT_RUN': '', 'AK_PARENT_RUN': '', 'AK_RUN_LOG': '', 'AK_RUN_ROLE': '',
            'AK_RUN_DEPTH': '0', 'AK_MAX_RUNS': '0', 'AGENTKIT_RUN_DIR': '',
            'ACME_SEAT_MARKER': 'carried-to-server', 'PYTHONDONTWRITEBYTECODE': '1'}))
        for key in ('TMUX', 'TMUX_PANE', 'AGENTKIT_ACCOUNT', 'CODEX_SQLITE_HOME',
                    'AGENTKIT_CODEX_CAPTURE', 'AGENTKIT_CODEX_RECEIPT', 'FAKE_PAIRING'):
            self.stack.enter_context(patch.dict(os.environ))
            os.environ.pop(key, None)
        self.stack.enter_context(patch.object(config, 'HOME', self.root / '.agentkit'))
        for key in ('RUNS', 'WT', 'STATE', 'SECRETS', 'TMP', 'ENV', 'WORK'):
            self.stack.enter_context(patch.object(config, key, config.HOME / key.lower()))
        config.ensure_dirs()
        self.cwd = self.root / 'acme'
        self.cwd.mkdir()
        (self.root / '.codex').mkdir()
        (self.root / '.codex/auth.json').write_text(json.dumps({
            'tokens': {'access_token': 'acme-token', 'account_id': 'acme-account'}}))
        self.cfg = config.load()
        config.save_session(self.cfg, 'acme-seat', 'astra', ['astra'], {'cwd': str(self.cwd)})
        self.procs = []
        self.addCleanup(self.cleanup)

    def fake(self, name, code):
        p = self.bin / name
        p.write_text(f'#!{sys.executable}\n' + code)
        p.chmod(0o755)

    def cleanup(self):
        for p, log in self.procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            log.close()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.05)
        logs = '\n'.join(p.read_text() for p in self.root.glob('launch-*.log'))
        self.fail('fake seat did not reach expected state\n' + logs)

    def start(self, owned=None, name="acme-seat", receipt=None, ready=True, direct=False):
        receipt = receipt or codex.prepare(name, self.cwd, owned)
        env = {**os.environ, codex.RECEIPT_ENV: str(receipt), "AGENTKIT_SESSION": name}
        args = ['bash', str(REPO / 'adapters/codex.sh'), 'interactive', 'default', 'high']
        if owned:
            args.append(owned)
        command = shlex.split(subprocess.run(
            args, env=env, text=True, capture_output=True, check=True).stdout)
        if direct:
            command = command[command.index(str(REPO / 'tools/codex-seat.py')) - 1:]
        log = (self.root / f'launch-{len(self.procs)}.log').open('w')
        proc = subprocess.Popen(command, env=env, cwd=self.cwd,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)
        self.procs.append((proc, log))
        (self.root / ('seat-pid-' + name)).write_text(str(proc.pid))
        remote = json.loads(receipt.read_text())['remote']
        home = config.STATE / ('codex-remote-' + remote)
        if ready:
            self.wait_for(lambda: (home / 'fake-tui.json').exists())
        return proc, home, receipt

    def stop(self, proc, home, name="acme-seat"):
        server = json.loads((home / 'fake-server.json').read_text())
        tui = json.loads((home / 'fake-tui.json').read_text())
        subprocess.run(['tmux', '-L', 'agentkit-test', 'kill-session', '-t', f'={name}:'],
                       check=True)
        proc.wait(timeout=10)
        self.wait_for(lambda: not (home / 'connection.json').exists())
        for pid in (server['pid'], tui['pid']):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        (home / 'fake-tui.json').unlink()
        (home / 'fake-server.json').unlink()
        (home / 'fake-monitor-closed').unlink(missing_ok=True)

    def test_receipts_are_published_after_writing_json(self):
        # Hold the fake between opening a receipt and writing its contents.
        for receipt in ('fake-server', 'fake-tui'):
            with self.subTest(receipt):
                self.fake('codex', f'''from pathlib import Path
import time
write_text = Path.write_text
def paused_write(path, text, *args, **kwargs):
    if not path.name.startswith('{receipt}.'):
        return write_text(path, text, *args, **kwargs)
    with path.open('w') as output:
        gate = Path.home() / 'release-{receipt}'
        gate.with_suffix('.waiting').touch()
        while not gate.exists():
            time.sleep(.05)
        return output.write(text)
Path.write_text = paused_write
''' + FAKE)
                proc, home, _ = self.start(ready=False)
                gate = self.root / f'release-{receipt}'
                try:
                    self.wait_for(lambda: gate.with_suffix('.waiting').exists())
                    self.assertFalse((home / f'{receipt}.json').exists(),
                                     'a receipt must not expose unfinished JSON')
                finally:
                    gate.touch()
                self.wait_for(lambda: (home / 'fake-tui.json').exists())
                self.stop(proc, home)

    def test_server_owns_hooks_rulebook_environment_and_tui_connection(self):
        proc, home, receipt = self.start()
        server = json.loads((home / 'fake-server.json').read_text())
        tui = json.loads((home / 'fake-tui.json').read_text())
        args = server['argv']
        self.assertEqual(args[:2], ['app-server', '--remote-control'])
        self.assertEqual(args[args.index('--listen') + 1],
                         tui['argv'][tui['argv'].index('--remote') + 1])
        for event in ('SessionStart', *codex.SEAT_EVENTS):
            self.assertTrue(any(a.startswith('hooks.' + event + '=') for a in args))
        self.assertTrue(any(a.startswith('hooks.state=') for a in args))
        self.assertIn('developer_instructions=' + config.rulebook_path('acme-seat').read_text(), args)
        self.assertEqual(server['env']['ACME_SEAT_MARKER'], 'carried-to-server')
        self.assertEqual(server['env']['AGENTKIT_SESSION'], 'acme-seat')
        self.assertEqual(server['env'][codex.CAPTURE_ENV], str(receipt))
        self.assertNotIn(codex.RECEIPT_ENV, server['env'])
        self.assertEqual(server['env']['CODEX_HOME'], str(home))
        self.assertNotIn('CODEX_SQLITE_HOME', server['env'])
        self.assertIn('sqlite_home=' + json.dumps(str(home)), args)
        self.assertIn('shell_environment_policy.set.CODEX_HOME=' +
                      json.dumps(str(self.root / '.codex')), args)
        self.assertEqual((home / 'auth.json').resolve(), self.root / '.codex/auth.json')
        record = config.session_records()['acme-seat']
        self.assertEqual(codex.conversation(record), 'acme-thread')
        self.assertEqual(json.loads((home / 'fake-working.json').read_text())['event'], 'UserPromptSubmit')
        self.assertEqual(json.loads((config.STATE / 'hook-acme-seat.json').read_text())['event'], 'Stop')
        config.update_session('acme-seat', session_title='acme-seat')
        record = config.session_records()['acme-seat']
        (home / 'session_index.jsonl').write_text(json.dumps({
            'id': 'acme-thread', 'thread_name': 'acme-seat'}) + '\n')
        self.assertEqual(codex.session_title(record), 'acme-seat')
        (home / 'session_index.jsonl').write_text(json.dumps({
            'id': 'acme-thread', 'thread_name': 'codex-made'}) + '\n')
        self.assertEqual(codex.session_title(record), '')
        self.stop(proc, home)

    def test_stop_and_resume_keep_identity_and_owned_conversation(self):
        proc, home, receipt = self.start()
        before = json.loads((home / 'fake-server.json').read_text())['pid']
        self.stop(proc, home)
        proc, resumed, new_receipt = self.start('acme-thread')
        self.assertEqual(home, resumed)
        self.assertNotEqual(receipt, new_receipt)
        self.assertFalse(receipt.exists())
        self.assertNotEqual(before, json.loads((home / 'fake-server.json').read_text())['pid'])
        argv = json.loads((home / 'fake-tui.json').read_text())['argv']
        self.assertEqual(argv[argv.index('resume') + 1], 'acme-thread')
        self.assertEqual(codex.conversation(config.session_records()['acme-seat']), 'acme-thread')
        self.stop(proc, home)

    def test_opening_or_resuming_unpaired_sends_no_notice(self):
        with patch.dict(os.environ, {'FAKE_PAIRING': '1'}):
            proc, home, _ = self.start()
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            self.assertEqual(notify_events(), [])
            self.assertFalse((self.root / 'pairings.jsonl').exists())
            self.assertIsNone(notify.last('acme-seat', include_seen=True))
            self.stop(proc, home)
            proc, resumed, _ = self.start('acme-thread')
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            self.stop(proc, resumed)
        self.assertEqual(notify_events(), [])
        self.assertFalse((self.root / 'pairings.jsonl').exists())

    def test_pairing_is_requested_explicitly_without_a_needs_notice(self):
        with patch.dict(os.environ, {'FAKE_PAIRING': '1'}):
            proc, home, _ = self.start()
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            config.session_path('acme-before').write_text(json.dumps({'renamed': 'acme-seat'}))
            # Project folders often have the seat's name; pairing chooses the seat.
            (self.root / 'acme-seat').mkdir()
            (self.root / 'acme-before').mkdir()
            for target in ('acme-seat', 'acme-before', str(home)):
                result = subprocess.run([sys.executable, str(REPO / 'tools/codex-seat.py'),
                                         '--pair', target], capture_output=True, text=True,
                                        env=os.environ, cwd=self.root, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'Pairing code: ACME-1234\n')
            requests = [json.loads(line) for line in
                        (self.root / 'pairings.jsonl').read_text().splitlines()]
            self.assertEqual(requests, [{'manualCode': True}] * 3)
            self.assertEqual(notify_events(), [])
            self.assertIsNone(proc.poll())
            self.stop(proc, home)

    def legacy_card(self, home):
        environment = next(iter(json.loads((home / 'agentkit-enrollments.json').read_text())))
        module = runpy.run_path(str(REPO / 'tools/codex-seat.py'))
        key = module['pairing_key'](environment)
        notify._write_event({'id': key, 'source': 'codex-pair:' + environment,
                             'session': None, 'kind': 'needs', 'status': 'pending',
                             'payload': {'embeds': [{'title': 'Needs you · acme-seat'}]},
                             'next_attempt': 0, 'attempts': 0})
        return key

    def test_resuming_retires_an_old_optional_pairing_card(self):
        with patch.dict(os.environ, {'FAKE_PAIRING': '1'}):
            proc, home, _ = self.start()
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            self.stop(proc, home)
            key = self.legacy_card(home)
            proc, resumed, _ = self.start('acme-thread')
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            event = notify._read_event(key)
            self.assertEqual(event['closed'], 'Pairing optional')
            self.assertEqual(event['status'], 'disabled')
            self.assertIsNone(event['next_attempt'])
            self.assertFalse((self.root / 'pairings.jsonl').exists())
            self.stop(proc, resumed)

    def test_two_seats_have_separate_servers_and_identities(self):
        first, a, _ = self.start()
        config.save_session(self.cfg, 'acme-other', 'astra', ['astra'], {'cwd': str(self.cwd)})
        with patch.dict(os.environ, {'FAKE_THREAD': 'acme-other-thread'}):
            second, b, _ = self.start(name='acme-other')
        self.wait_for(lambda: (a / 'fake-monitor-closed').exists() and
                      (b / 'fake-monitor-closed').exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual({c['body']['name'] for c in calls}, {'acme-seat', 'acme-other'})
        self.assertNotEqual((a / 'installation_id').read_text(), (b / 'installation_id').read_text())
        self.assertNotEqual(a, b)
        self.assertNotEqual(json.loads((a / 'connection.json').read_text())['socket'],
                            json.loads((b / 'connection.json').read_text())['socket'])
        self.stop(second, b, 'acme-other')
        self.assertIsNone(first.poll())
        self.assertEqual(codex.conversation(config.session_records()['acme-seat']), 'acme-thread')
        self.stop(first, a)

    def test_exiting_tui_stops_its_server(self):
        with patch.dict(os.environ, {'FAKE_HOLD': ''}):
            proc, home, _ = self.start()
        proc.wait(timeout=10)
        self.assertFalse((home / 'connection.json').exists())
        pid = json.loads((home / 'fake-server.json').read_text())['pid']
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertFalse((self.root / 'pairings.jsonl').exists())

    def test_live_account_switch_preserves_enrollment_and_pairing(self):
        with patch.dict(os.environ, {'FAKE_PAIRING': '1'}):
            proc, home, receipt = self.start()
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            identity = (home / 'installation_id').read_bytes()
            database = (home / 'state_5.sqlite').read_bytes()
            # orch prepares the new receipt before respawn-pane kills the old pane.
            new_receipt = codex.prepare('acme-seat', self.cwd, 'acme-thread')
            self.assertFalse(receipt.exists())
            self.stop(proc, home)
            account = self.root / '.codex-acme'
            account.mkdir()
            (account / 'auth.json').write_bytes((self.root / '.codex/auth.json').read_bytes())
            with patch.dict(os.environ, {'AGENTKIT_ACCOUNT': 'acme'}):
                proc, resumed, _ = self.start('acme-thread', receipt=new_receipt)
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            self.assertEqual(resumed, home)
            self.assertEqual((home / 'installation_id').read_bytes(), identity)
            self.assertEqual((home / 'state_5.sqlite').read_bytes(), database)
            self.assertEqual((home / 'auth.json').resolve(), account / 'auth.json')
            self.assertEqual(codex.conversation(config.session_records()['acme-seat']), 'acme-thread')
            self.assertEqual(notify_events(), [])
            self.assertFalse((self.root / 'pairings.jsonl').exists())
            self.stop(proc, home)

    def test_new_launch_waits_for_old_cleanup_before_reusing_home(self):
        gate = self.root / 'release-old-server'
        with patch.dict(os.environ, {'FAKE_STOP_GATE': str(gate)}):
            old, home, _ = self.start()
        before = json.loads((home / 'fake-server.json').read_text())['pid']
        receipt = codex.prepare('acme-seat', self.cwd, 'acme-thread')
        old.send_signal(signal.SIGTERM)
        self.wait_for(lambda: Path(str(gate) + '.waiting').exists())
        proc, _, _ = self.start('acme-thread', receipt=receipt, ready=False)
        time.sleep(.3)
        self.assertEqual(json.loads((home / 'fake-server.json').read_text())['pid'], before)
        gate.touch()
        old.wait(timeout=10)
        self.wait_for(lambda: json.loads((home / 'fake-server.json').read_text())['pid'] != before)
        self.wait_for(lambda: (home / 'connection.json').exists())
        client_type = runpy.run_path(str(REPO / 'tools/codex-seat.py'))['Client']
        client = client_type(json.loads((home / 'connection.json').read_text())['socket'])
        try:
            self.assertEqual(client.call('remoteControl/status/read')['status'], 'connected')
        finally:
            client.close()
        self.stop(proc, home)

    def test_sigkill_wrapper_stops_server_and_tui(self):
        proc, home, _ = self.start(direct=True)
        server = json.loads((home / 'fake-server.json').read_text())
        tui = json.loads((home / 'fake-tui.json').read_text())
        proc.kill()
        proc.wait(timeout=10)
        self.wait_for(lambda: not (home / 'connection.json').exists())
        for pid in (server['pid'], tui['pid']):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_legacy_cli_opens_local_seat_without_remote_flags(self):
        with patch.dict(os.environ, {'FAKE_UNSUPPORTED': '1'}):
            proc, home, _ = self.start(ready=False)
            self.assertEqual(proc.wait(timeout=10), 0)
        args = json.loads((self.root / 'last-command.json').read_text())
        self.assertNotIn('--remote', args)
        self.assertFalse(home.exists())
        self.assertTrue(any(a.startswith('developer_instructions=') for a in args))

    def test_forget_removes_enrollment_only_after_server_stops(self):
        with patch.dict(os.environ, {'FAKE_PAIRING': '1', 'FAKE_DELETE_BUSY': '1'}):
            proc, home, receipt = self.start()
            self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
            server = json.loads((home / 'fake-server.json').read_text())['pid']
            codex.forget(config.session_records()['acme-seat'])
            proc.wait(timeout=10)
            self.wait_for(lambda: not home.exists())
            self.assertFalse(home.with_suffix('.forgotten').exists())
            self.assertFalse(home.with_suffix('.lock').exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(server, 0)
        self.assertFalse(receipt.exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual([c['method'] for c in calls], ['PATCH', 'DELETE', 'DELETE'])
        self.assertEqual(calls[0]['body'], {'name': 'acme-seat'})
        self.assertEqual(notify_events(), [])

    def test_forget_stopped_seat_removes_its_remote_enrollment(self):
        proc, home, _ = self.start()
        self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
        self.stop(proc, home)
        key = self.legacy_card(home)
        codex.forget(config.session_records()['acme-seat'])
        self.assertFalse(home.exists())
        self.assertFalse(home.with_suffix('.forgotten').exists())
        self.assertFalse(home.with_suffix('.lock').exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual([c['method'] for c in calls], ['PATCH', 'DELETE'])
        event = notify._read_event(key)
        self.assertEqual(event['closed'], 'Closed')
        self.assertEqual(event['status'], 'disabled')
        self.assertIsNone(event['next_attempt'])

    def test_forget_offline_still_forgets_and_retries_enrollment_later(self):
        proc, home, _ = self.start()
        self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
        self.stop(proc, home)
        record = config.session_records()['acme-seat']
        with patch.dict(os.environ, {'FAKE_HTTP_OFFLINE': '1'}):
            codex.forget(record)
        self.assertFalse(codex.path_for(record).exists())
        self.assertTrue(home.exists())
        self.assertTrue(home.with_suffix('.forgotten').exists())
        self.assertTrue((home / 'agentkit-enrollments.json').exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual([c['method'] for c in calls], ['PATCH'])
        codex.forget(record)
        self.assertFalse(home.exists())
        self.assertFalse(home.with_suffix('.forgotten').exists())
        self.assertFalse(home.with_suffix('.lock').exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual([c['method'] for c in calls], ['PATCH', 'DELETE'])

    def test_forget_retries_after_persistent_delete_conflict(self):
        proc, home, _ = self.start()
        self.wait_for(lambda: (home / 'fake-monitor-closed').exists())
        self.stop(proc, home)
        record = config.session_records()['acme-seat']
        with patch.dict(os.environ, {'FAKE_DELETE_BUSY_ALWAYS': '1'}):
            codex.forget(record)
        self.assertFalse(codex.path_for(record).exists())
        self.assertTrue(home.exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual([c['method'] for c in calls], ['PATCH'] + ['DELETE'] * 6)
        codex.forget(record)
        self.assertFalse(home.exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual([c['method'] for c in calls], ['PATCH'] + ['DELETE'] * 7)

    def test_forget_recovers_enrollment_if_pane_exited_before_monitor(self):
        with patch.dict(os.environ, {'FAKE_HOLD': ''}):
            proc, home, _ = self.start()
        proc.wait(timeout=10)
        (home / 'agentkit-enrollments.json').unlink()
        codex.forget(config.session_records()['acme-seat'])
        self.assertFalse(home.exists())
        calls = [json.loads(s) for s in (self.root / 'remote-http.jsonl').read_text().splitlines()]
        self.assertEqual(calls[-1]['method'], 'DELETE')

    def test_workers_keep_the_callers_home_variables(self):
        with patch.dict(os.environ, {'CODEX_SQLITE_HOME': 'acme-private',
                                     codex.CAPTURE_ENV: 'acme-receipt'}):
            child = config.child_env()
        self.assertEqual(child['CODEX_HOME'], str(self.root / '.codex'))
        self.assertEqual(child['CODEX_SQLITE_HOME'], 'acme-private')
        self.assertNotIn(codex.CAPTURE_ENV, child)


def notify_events():
    from agentkit import notify
    return list(notify.outbox().glob('*.json'))


if __name__ == '__main__':
    unittest.main()
