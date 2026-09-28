"""Per-seat app servers, lifecycle and pairing. All processes and homes are fakes."""
from contextlib import ExitStack
import json
import os
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
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=REPO,
                                                                           prefix='.remote-')))
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
            'TMPDIR': str(REPO), 'PATH': f'{self.bin}:{os.environ["PATH"]}',
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
        (self.root / '.codex/auth.json').write_text('{"auth_mode":"chatgpt"}')
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

    def start(self, owned=None, name="acme-seat"):
        receipt = codex.prepare(name, self.cwd, owned)
        env = {**os.environ, codex.RECEIPT_ENV: str(receipt), "AGENTKIT_SESSION": name}
        args = ['bash', str(REPO / 'adapters/codex.sh'), 'interactive', 'default', 'high']
        if owned:
            args.append(owned)
        command = subprocess.run(args, env=env, text=True, capture_output=True, check=True).stdout
        log = (self.root / f'launch-{len(self.procs)}.log').open('w')
        proc = subprocess.Popen(shlex.split(command), env=env, cwd=self.cwd,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)
        self.procs.append((proc, log))
        (self.root / ('seat-pid-' + name)).write_text(str(proc.pid))
        remote = json.loads(receipt.read_text())['remote']
        home = config.STATE / ('codex-remote-' + remote)
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
        self.assertTrue(any(a.startswith('developer_instructions=# You are the orchestrator')
                            for a in args))
        self.assertEqual(server['env']['ACME_SEAT_MARKER'], 'carried-to-server')
        self.assertEqual(server['env']['AGENTKIT_SESSION'], 'acme-seat')
        self.assertEqual(server['env'][codex.CAPTURE_ENV], str(receipt))
        self.assertNotIn(codex.RECEIPT_ENV, server['env'])
        self.assertEqual(server['env']['CODEX_HOME'], str(home))
        self.assertEqual(server['env']['CODEX_SQLITE_HOME'], str(home))
        self.assertEqual((home / 'auth.json').resolve(), self.root / '.codex/auth.json')
        record = config.session_records()['acme-seat']
        self.assertEqual(codex.conversation(record), 'acme-thread')
        self.assertEqual(json.loads((home / 'fake-working.json').read_text())['event'], 'UserPromptSubmit')
        self.assertEqual(json.loads((config.STATE / 'hook-acme-seat.json').read_text())['event'], 'Stop')
        (home / 'session_index.jsonl').write_text(json.dumps({
            'id': 'acme-thread', 'thread_name': 'acme-seat'}) + '\n')
        self.assertEqual(codex.session_title(record), 'acme-seat')
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

    def test_pairing_is_one_card_with_exact_step_even_after_resume(self):
        with patch.dict(os.environ, {'FAKE_PAIRING': '1'}):
            proc, home, _ = self.start()
            self.wait_for(lambda: (home / 'agentkit-pairing.json').exists() and
                          (home / 'agentkit-pairing.json').stat().st_size > 0)
            # The regular health tick sees the same question; it must not send a
            # second, generic Needs you card after the pairing card.
            card = notify._card_read('acme-seat')
            with patch.object(notify, '_attached', return_value=False):
                for _ in range(3):
                    notify.needs_transition('acme-seat', card,
                                            {'reason': 'Pair the ChatGPT app'}, time.time() + 120)
            self.stop(proc, home)
            proc, resumed, _ = self.start('acme-thread')
            time.sleep(.5)
            self.stop(proc, resumed)
        events = [json.loads(p.read_text()) for p in notify_events()]
        self.assertEqual(len(events), 1)
        self.assertTrue(notify._card_read('acme-seat')['sent'])
        card = events[0]['payload']['embeds'][0]
        self.assertEqual(card['title'], 'Needs you · acme-seat')
        self.assertIn('ChatGPT app', card['description'])
        self.assertIn('ACME-1234', card['description'])
        self.assertIn('--pair', card['description'])
        self.assertEqual(len((self.root / 'pairings.jsonl').read_text().splitlines()), 1)

    def test_two_seats_have_separate_servers_and_identities(self):
        first, a, _ = self.start()
        config.save_session(self.cfg, 'acme-other', 'astra', ['astra'], {'cwd': str(self.cwd)})
        with patch.dict(os.environ, {'FAKE_THREAD': 'acme-other-thread'}):
            second, b, _ = self.start(name='acme-other')
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

    def test_seat_variables_do_not_reach_workers(self):
        with patch.dict(os.environ, {'CODEX_SQLITE_HOME': 'acme-private',
                                     codex.CAPTURE_ENV: 'acme-receipt'}):
            child = config.child_env()
        self.assertNotIn('CODEX_HOME', child)
        self.assertNotIn('CODEX_SQLITE_HOME', child)
        self.assertNotIn(codex.CAPTURE_ENV, child)


def notify_events():
    from agentkit import notify
    return list(notify.outbox().glob('*.json'))


if __name__ == '__main__':
    unittest.main()
