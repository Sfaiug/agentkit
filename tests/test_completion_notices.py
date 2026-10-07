"""One owner's completion through late internal turns, on every configured harness.

Offline: temporary seat state and transcripts, fake tmux and a local webhook.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, harness, menu, notify, orch, plan, watch
from agentkit.harness import claude


class CompletionNotices(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = 10000
        self.requests = []
        self.response_status = 200
        owner = self

        class Webhook(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.command, payload))
                self.send_response(owner.response_status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'id': str(len(owner.requests))}).encode())

            do_POST = do_PATCH = handle_request

        server = ThreadingHTTPServer(('127.0.0.1', 0), Webhook)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.stack.enter_context(patch.dict(os.environ, {
            notify.SINK_ENV: f'http://127.0.0.1:{server.server_port}/hook',
            'AGENTKIT_DISCORD_USER_ID': '123456789012345678', 'AK_RUN_ROLE': '',
            'AGENTKIT_RUN': '', 'AK_PARENT_RUN': '', 'AK_RUN_LOG': '',
            'CLAUDE_CONFIG_DIR': str(self.root / '.claude'),
            'CODEX_HOME': str(self.root / '.codex'),
            'GROK_HOME': str(self.root / '.grok'),
            'XDG_CONFIG_HOME': str(self.root / '.config'),
            'XDG_DATA_HOME': str(self.root / '.local/share'),
        }))
        self.stack.enter_context(patch.object(notify.time, 'time', side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(notify, 'terminal_notice'))
        self.stack.enter_context(patch.object(orch, 'tmux_out', return_value=(1, 'fake tmux')))
        # Supply only screen/auth facts; the real state ladder still decides from notices,
        # questions and runs. No harness, model, login or tmux process is started.
        decide = watch.session_state

        def state(name, **facts):
            record = config.session_records().get(name, {})
            if facts.get('session') is None:
                facts['session'] = {**record, 'name': name}
            facts.setdefault('cfg', self.cfg)
            facts.setdefault('harness', orch.seat_plugin(record))
            facts.setdefault('live', {'state': 'prompt'})
            facts.setdefault('auth_out', {})
            facts.setdefault('gh_out', {})
            facts.setdefault('token_out', {})
            return decide(name, **facts)

        self.stack.enter_context(patch.object(watch, 'session_state', side_effect=state))
        self.name = 'fix-api'
        self.seat(self.name)

    def seat(self, name, model=None, *, created=10):
        model = model or self.cfg['defaults']['workers'][0]
        config.save_session(self.cfg, name, model, self.cfg['defaults']['workers'],
                            {'created': created, 'cwd': str(self.root / 'acme'),
                             'conversation': 'thread', 'id_source': harness.LAUNCHER})

    def checked(self, *outcomes, name=None):
        config.plan_path(name or self.name).write_text(''.join(
            f'- [x] {outcome}\n' for outcome in outcomes))

    def declare(self, text='API shipped', *, name=None):
        self.assertEqual(notify.shaped('done', text, session=name or self.name), 0)

    def posted(self, name=None, kind='done'):
        title = f'{notify.TITLES[kind]} · {name or self.name}'
        return [payload for method, payload in self.requests
                if method == 'POST' and payload['embeds'][0]['title'] == title]

    def internal_turn(self, name=None):
        name = name or self.name
        self.now += 100
        notify.clear(name)
        self.assertEqual(notify.transition(name, answer={
            'word': 'working', 'reason': 'late run handback', 'since': self.now}), 0)

    def test_one_completion_through_late_handbacks_on_every_configured_model(self):
        for index, model in enumerate(self.cfg['models']):
            name = f'acme-{index}'
            with self.subTest(model=model, harness=config.model(self.cfg, model)['harness']):
                self.seat(name, model, created=index + 20)
                self.checked('API uses the requested parameters', name=name)
                self.declare(name=name)
                for summary in ('The late run passed too', 'Everything remains live'):
                    self.internal_turn(name)
                    self.declare(summary, name=name)
                self.assertEqual(len(self.posted(name)), 1)
                payload = self.posted(name)[0]
                self.assertEqual(payload['content'], '<@123456789012345678>')
                self.assertEqual(set(payload['embeds'][0]), {'title', 'color', 'timestamp'})
                self.assertEqual(payload['embeds'][0]['color'], notify.COLORS['done'])

    def test_new_checked_work_sends_without_an_intermediate_tick(self):
        self.checked('API accepts the new parameters')
        self.declare()
        self.now += 100
        self.checked('API accepts the new parameters', 'The export uses the same parameters')
        self.declare('The next job is shipped')
        self.assertEqual(len(self.posted()), 2)
        self.internal_turn()
        self.declare('A late PASS confirms the next job')
        self.assertEqual(len(self.posted()), 2)

    def test_proof_refresh_and_reordering_do_not_create_another_completion(self):
        lines = [f'- [x] {outcome} · your eye · acme · written 2026-01-01 12:00'
                 ' · done your yes 2026-01-02 12:00' for outcome in ('API looks right', 'Export looks right')]
        config.plan_path(self.name).write_text('\n'.join(lines) + '\n')
        self.declare()
        self.internal_turn()
        config.plan_path(self.name).write_text('\n'.join(
            line.replace('done your yes 2026-01-02', 'done your yes 2026-01-03')
            for line in reversed(lines)) + '\n')
        self.declare('Proof refreshed; still shipped')
        self.assertEqual(len(self.posted()), 1)

    def test_check_proofs_refresh_on_main_without_reannouncing_the_work(self):
        repo = config.CODE / 'acme'
        repo.mkdir(parents=True)
        self.stack.enter_context(patch.dict(os.environ, {
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}))
        self.stack.enter_context(patch.object(plan.os, 'killpg'))

        def git(*args):
            return subprocess.run(['git', '-C', str(repo), *args], check=True,
                                  capture_output=True, text=True, timeout=30).stdout.strip()

        git('init', '-q', '-b', 'main')
        git('config', 'user.name', 'Completion test')
        git('config', 'user.email', 'completion@localhost')
        (repo / 'base.txt').write_text('base\n')
        git('add', '.')
        git('commit', '-q', '-m', 'Base')
        origin = self.root / 'origin.git'
        subprocess.run(['git', 'clone', '-q', '--bare', str(repo), str(origin)],
                       check=True, capture_output=True, timeout=30)
        git('remote', 'add', 'origin', str(origin))
        config.update_session(self.name, repo=str(repo))
        plan.add(self.name, 'API shipped', check='test -f shipped.txt')
        with self.assertRaises(notify.Refused):
            self.declare('Not live yet')
        (repo / 'shipped.txt').write_text('shipped\n')
        git('add', '.')
        git('commit', '-q', '-m', 'Ship API')
        git('push', '-q', 'origin', 'main')
        self.declare()
        before = config.plan_path(self.name).read_text()
        self.internal_turn()
        (repo / 'base.txt').write_text('unrelated update\n')
        git('add', '.')
        git('commit', '-q', '-m', 'Unrelated update')
        git('push', '-q', 'origin', 'main')
        self.declare('The check passed on newer main too')
        self.assertNotEqual(config.plan_path(self.name).read_text(), before)
        self.assertEqual(len(self.posted()), 1)

    def test_history_still_deduplicates_after_card_loss_and_rename(self):
        self.checked('API shipped')
        self.declare()
        self.internal_turn()
        config.card_path(self.name).unlink()
        config.rename_session(self.name, 'api-ready')
        self.now += 100
        self.declare('Late report after rename', name='api-ready')
        self.assertEqual(len(self.posted()) + len(self.posted('api-ready')), 1)

    def owner_transcript(self):
        # The plugin's real owner reader and occurrence-based typing receipts are used.
        model = next(name for name in self.cfg['models']
                     if config.model(self.cfg, name)['harness'] == claude.__name__.rsplit('.', 1)[-1])
        self.seat(self.name, model)
        record = config.session_records()[self.name]
        path = claude.transcript_path(record, 'thread')
        path.parent.mkdir(parents=True)
        path.touch()
        return path

    def append_owner(self, path, at, text):
        with path.open('a') as out:
            out.write(json.dumps({'type': 'user',
                'timestamp': datetime.fromtimestamp(at, timezone.utc).isoformat(),
                'message': {'role': 'user', 'content': text}}) + '\n')

    def receipt(self, text, source, after):
        record = config.session_records()[self.name]
        with config.seat_file('input', self.name).open('a') as out:
            out.write(json.dumps({'text': text, 'source': source, 'after': after,
                'harness': orch.seat_plugin(record).name, 'conversation': 'thread',
                'at': self.now}) + '\n')

    def test_owner_receipts_exclude_internal_input_but_keep_a_later_identical_request(self):
        path = self.owner_transcript()
        self.append_owner(path, 20, 'Build the API')
        self.declare()
        self.internal_turn()
        self.receipt('Build the API', 'seat:acme-peer', 1)
        self.append_owner(path, 30, 'Build the API')
        self.declare('Peer handback received')
        self.assertEqual(len(self.posted()), 1)
        # A relayed real owner input is kept, even with the same words as the peer receipt.
        self.receipt('Build the API', 'owner', 2)
        self.append_owner(path, 40, 'Build the API')
        self.now += 100
        self.declare('New owner job shipped')
        self.assertEqual(len(self.posted()), 2)

    def test_a_plan_takes_precedence_over_a_later_information_question(self):
        path = self.owner_transcript()
        self.append_owner(path, 20, 'Build the API')
        self.checked('API shipped')
        self.declare()
        self.append_owner(path, 30, 'What caused the earlier failure?')
        self.internal_turn()
        self.declare('Earlier failure explained; API remains shipped')
        self.assertEqual(len(self.posted()), 1)

    def test_a_missing_owner_source_does_not_reannounce_the_completed_work(self):
        path = self.owner_transcript()
        self.append_owner(path, 20, 'Build the API')
        self.declare()
        self.internal_turn()
        path.unlink()
        self.declare('Internal handback while the transcript is unavailable')
        self.assertEqual(len(self.posted()), 1)

    def test_a_legacy_sent_completion_adopts_identity_without_another_card(self):
        self.checked('API shipped')
        self.declare()
        paths = [config.card_path(self.name), config.notify_path(self.name),
                 *notify.outbox().glob('*.json')]
        for path in paths:
            old = json.loads(path.read_text())
            old.pop('completion', None)
            old.pop('completed', None)
            path.write_text(json.dumps(old))
        self.now += 100
        self.declare('The API remains shipped after upgrade')
        self.assertEqual(len(self.posted()), 1)
        self.internal_turn()
        config.card_path(self.name).unlink()
        self.declare('Another handback after losing the episode file')
        self.assertEqual(len(self.posted()), 1)
        self.checked('API shipped', 'Export shipped')
        self.declare('A new job after the legacy card adopted its identity')
        self.assertEqual(len(self.posted()), 2)

    def test_a_missing_owner_source_preserves_a_newer_pending_completion(self):
        path = self.owner_transcript()
        self.append_owner(path, 20, 'Build the API')
        self.declare()
        self.now += 100
        self.append_owner(path, 30, 'Build the export')
        pending = config.RUNS / 'acme-run'
        pending.mkdir()
        state = {'run_id': pending.name, 'state': 'running', 'launched_session': self.name,
                 'started_at': self.now, 'pid': 0}
        (pending / 'run.json').write_text(json.dumps(state))
        self.declare('Export ready pending its run')
        self.assertEqual(len(self.posted()), 1)
        path.unlink()
        self.now += 100
        self.declare('Internal handback while the transcript is unavailable')
        state.update(state='pass', verdict='PASS', reported=True, finished_at=self.now + 1)
        (pending / 'run.json').write_text(json.dumps(state))
        self.now += 100
        self.assertEqual(notify.transition(self.name), 0)
        self.assertEqual(len(self.posted()), 2)

    def test_a_later_question_keeps_its_alert_without_reannouncing_the_job(self):
        self.checked('API shipped')
        self.declare()
        self.now += 100
        self.assertEqual(notify.shaped('needs', 'Which export format?', session=self.name), 0)
        self.assertEqual(len(self.posted(kind='needs')), 1)
        self.declare('Question settled; API remains shipped')
        self.assertEqual(len(self.posted()), 1)
        patches = [payload for method, payload in self.requests if method == 'PATCH']
        self.assertEqual(patches[-1]['embeds'][0]['title'], f'Done · {self.name}')

    def test_a_real_question_and_unfinished_work_still_hold_the_completion(self):
        self.checked('API shipped')
        self.assertEqual(notify.shaped('needs', 'Which export format?', session=self.name), 0)
        self.assertEqual(len(self.posted(kind='needs')), 1)
        pending = config.RUNS / 'acme-run'
        pending.mkdir()
        record = {'run_id': pending.name, 'state': 'running', 'launched_session': self.name,
                  'started_at': self.now, 'pid': 0}
        (pending / 'run.json').write_text(json.dumps(record))
        self.declare()
        self.assertEqual(len(self.posted()), 0)
        record.update(state='pass', verdict='PASS', reported=True, finished_at=self.now + 1)
        (pending / 'run.json').write_text(json.dumps(record))
        self.now += 100
        self.assertEqual(notify.transition(self.name), 0)
        self.assertEqual(len(self.posted()), 1)
        patches = [payload for method, payload in self.requests if method == 'PATCH']
        self.assertEqual(patches[-1]['embeds'][0]['title'], f'Answered · {self.name}')
        self.assertEqual(patches[-1]['content'], '')
        self.assertEqual(patches[-1]['allowed_mentions'], {'parse': []})
        self.internal_turn()
        self.declare('The run handback confirms shipping')
        self.assertEqual(len(self.posted()), 1)
        self.checked('API shipped', 'New work still open')
        config.plan_path(self.name).write_text(
            config.plan_path(self.name).read_text().replace('[x] New work', '[ ] New work'))
        with self.assertRaises(notify.Refused):
            self.declare('Premature completion')
        self.assertEqual(len(self.posted()), 1)

    def test_delivery_retries_and_concurrent_declarations_keep_one_event(self):
        self.checked('API shipped')
        self.response_status = 503
        self.declare()
        self.internal_turn()
        with ThreadPoolExecutor(max_workers=3) as writers:
            results = list(writers.map(lambda at: notify.shaped(
                'done', f'Late handback {at}', session=self.name), range(6)))
        self.assertEqual(results, [0] * 6)
        events = [json.loads(path.read_text()) for path in notify.outbox().glob('*.json')]
        self.assertEqual(len(events), 1)
        self.response_status = 200
        self.now += 10000
        notify.retry_pending(log=lambda _: None)
        self.assertEqual(len(self.posted()), 2)  # one failed request and one successful retry
        self.assertEqual(json.loads(next(notify.outbox().glob('*.json')).read_text())['status'],
                         'delivered')
        self.internal_turn()
        self.declare('Retry succeeded, nothing new to announce')
        self.assertEqual(len(self.posted()), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
