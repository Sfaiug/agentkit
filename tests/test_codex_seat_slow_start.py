"""Codex seats wait for their own server and recover an interrupted backfill; offline."""
from contextlib import closing, ExitStack
import json
import os
from pathlib import Path
import runpy
import signal
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]

FAKE = '''import os
from pathlib import Path
import socket
import sqlite3
import sys
import time

home = Path(os.environ['CODEX_HOME'])
args = sys.argv[1:]
if '--remote' in args:
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(args[args.index('--remote') + 1].removeprefix('unix://'))
    (home / 'tui-started').touch()
    sys.exit(0)
assert args[0] == 'app-server'
if os.environ.get('FAKE_ERROR'):
    print('acme server failed to load config', file=sys.stderr, flush=True)
    sys.exit(23)
identity = home / 'installation_id'
if not identity.exists():
    identity.write_text('acme-seat-installation')
with sqlite3.connect(home / 'state_5.sqlite') as db:
    db.execute('CREATE TABLE IF NOT EXISTS backfill_state ('
               'id INTEGER PRIMARY KEY CHECK (id = 1), status TEXT NOT NULL, '
               'last_watermark TEXT, last_success_at INTEGER, updated_at INTEGER NOT NULL)')
    db.execute("INSERT OR IGNORE INTO backfill_state VALUES (1, 'pending', 'acme-rollout', NULL, 123)")
    status = db.execute('SELECT status FROM backfill_state').fetchone()[0]
    if status == 'running':
        print('timed out waiting for state db backfill', file=sys.stderr, flush=True)
        sys.exit(24)
    if status != 'complete':
        db.execute("UPDATE backfill_state SET status = 'running'")
    db.execute('CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY)')
    db.execute("INSERT OR IGNORE INTO threads VALUES ('acme-thread')")
if status != 'complete':
    (home / 'backfill-started').touch()
    time.sleep(float(os.environ.get('FAKE_DELAY', '0')))
    with sqlite3.connect(home / 'state_5.sqlite') as db:
        db.execute("UPDATE backfill_state SET status = 'complete'")
with socket.socket(socket.AF_UNIX) as server:
    server.bind(args[args.index('--listen') + 1].removeprefix('unix://'))
    server.listen()
    while True:
        client, _ = server.accept()
        client.close()
'''


class SlowStart(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix='.ak-test-codex-start-', dir=REPO))
        self.root = Path(directory)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'installation_id').write_text('acme-owner-installation')
        (self.source / 'state_5.sqlite').write_bytes(b'acme-owner-database')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('AK_', 'AGENTKIT_'))
               and k not in ('CODEX_HOME', 'CODEX_SQLITE_HOME', 'FAKE_ERROR', 'FAKE_DELAY')}
        env.update(HOME=str(self.root), CODEX_HOME=str(self.source))
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        self.api = runpy.run_path(str(REPO / 'tools/codex-seat.py'))['connected'].__globals__
        state = self.root / 'state'
        state.mkdir()
        self.stack.enter_context(patch.object(self.api['config'], 'STATE', state))
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps({'remote': 'acme-seat'}))
        self.home = self.api['seat_home'](receipt)
        self.fake = self.root / 'codex'
        self.fake.write_text(f'#!{sys.executable}\n' + FAKE)
        self.fake.chmod(0o755)
        client = Mock()
        client.call.return_value = {'status': 'disabled'}
        self.stack.enter_context(patch.dict(self.api, Client=lambda _path: client))
        # Keep the Unix socket short even in a long worktree path.
        make_runtime = tempfile.TemporaryDirectory
        self.stack.enter_context(patch.object(tempfile, 'TemporaryDirectory',
            side_effect=lambda **_kw: make_runtime(prefix='.ak-test-', dir=REPO)))

    def start(self, wanted=lambda: True):
        handlers = {sig: signal.getsignal(sig) for sig in
                    (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)}
        try:
            return self.api['connected']([str(self.fake)], self.home, wanted)
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)

    def backfill(self):
        with closing(sqlite3.connect(self.home / 'state_5.sqlite')) as db:
            return db.execute('SELECT * FROM backfill_state').fetchone()

    def test_socket_after_16_seconds_starts_seat(self):
        started = time.monotonic()
        with patch.dict(os.environ, FAKE_DELAY='16'):
            self.assertEqual(self.start(), 0)
        self.assertGreaterEqual(time.monotonic() - started, 16)
        self.assertTrue((self.home / 'tui-started').exists())

    def test_server_exit_fails_start_with_its_log(self):
        with patch.dict(os.environ, FAKE_ERROR='1'):
            with self.assertRaisesRegex(self.api['config'].Error,
                                        'Codex seat server did not start; see .*server.log'):
                self.start()
        self.assertIn('acme server failed to load config', (self.home / 'server.log').read_text())
        self.assertFalse((self.home / 'tui-started').exists())

    def test_closed_during_backfill_starts_next_try_and_keeps_private_state(self):
        with patch.dict(os.environ, FAKE_DELAY='16'):
            self.assertEqual(self.start(lambda: not (self.home / 'backfill-started').exists()), 0)
        before = self.backfill()
        self.assertEqual(before[1], 'running')
        self.assertFalse((self.home / 'tui-started').exists())
        identity = (self.home / 'installation_id').read_bytes()
        self.assertEqual(self.start(), 0)
        self.assertTrue((self.home / 'tui-started').exists())
        after = self.backfill()
        self.assertEqual(after[1], 'complete')
        self.assertEqual(after[2:], before[2:])
        self.assertEqual((self.home / 'installation_id').read_bytes(), identity)
        self.assertFalse((self.home / 'state_5.sqlite').is_symlink())
        self.assertFalse((self.home / 'installation_id').is_symlink())
        with closing(sqlite3.connect(self.home / 'state_5.sqlite')) as db:
            self.assertEqual(db.execute('SELECT id FROM threads').fetchall(), [('acme-thread',)])
        self.assertEqual((self.source / 'state_5.sqlite').read_bytes(), b'acme-owner-database')
        self.assertEqual((self.source / 'installation_id').read_text(), 'acme-owner-installation')

    def test_completed_backfill_is_kept_on_resume(self):
        self.assertEqual(self.start(), 0)
        before = self.backfill()
        (self.home / 'backfill-started').unlink()
        self.assertEqual(self.start(), 0)
        self.assertEqual(self.backfill(), before)
        self.assertFalse((self.home / 'backfill-started').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
