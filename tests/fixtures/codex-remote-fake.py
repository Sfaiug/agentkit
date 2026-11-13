"""Offline Codex stand-in: real Unix transport, invented conversations, no provider calls."""
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import socket
import socketserver
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from datetime import datetime, timezone

args = sys.argv[1:]
home = Path.home()

ch = Path(os.environ.get('CODEX_HOME', home / '.codex'))


def publish(name, data):
    # Tests read a receipt as soon as it exists, so it appears with all its JSON.
    part = ch / (name + '.tmp')
    part.write_text(json.dumps(data))
    part.replace(ch / (name + '.json'))


def frame(message, mask=b''):
    # A client masks each frame it sends and a server never does (RFC 6455, 5.1).
    data = json.dumps(message).encode()
    size = bytes([len(data)]) if len(data) < 126 else bytes([126]) + struct.pack('!H', len(data))
    if mask:
        size = bytes([128 | size[0]]) + size[1:]
        data = bytes(v ^ mask[i % 4] for i, v in enumerate(data))
    return bytes([129]) + size + mask + data


def receive(stream):
    # None once the other end has closed
    if not (first := stream.read(2)):
        return None
    size = first[1] & 127
    if size == 126:
        size = struct.unpack('!H', stream.read(2))[0]
    mask = stream.read(4) if first[1] & 128 else bytes(4)
    return json.loads(bytes(v ^ mask[i % 4] for i, v in enumerate(stream.read(size))))


if args == ['--help']:
    print('old CLI' if os.environ.get('FAKE_UNSUPPORTED') else '--dangerously-bypass-hook-trust')
    sys.exit(0)
if os.environ.get('FAKE_UNSUPPORTED') and args != ['--help']:
    assert '--remote' not in args and 'app-server' not in args
    (home / 'last-command.json').write_text(json.dumps(args))
    sys.exit(0)
if args[:1] == ['app-server'] and not os.environ.pop('FAKE_NATIVE', None):
    # npm's entry point, its child the native app server: two `codex` above each hook (0.167).
    # Like npm's, it hands on a signal that would stop it and ends with its child, so a server
    # still stopping (FAKE_STOP_GATE) holds its launch's cleanup.
    native = subprocess.Popen([sys.executable, *sys.argv], env={**os.environ, 'FAKE_NATIVE': '1'})
    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: native.send_signal(signum))
    sys.exit(native.wait())
if args[:1] == ['app-server']:
    assert '--remote-control' in args
    def orphaned(parent=os.getppid()):     # its entry point killed, it never outlives the test
        while os.getppid() == parent:
            time.sleep(.1)
        os._exit(1)
    threading.Thread(target=orphaned, daemon=True).start()
    path = args[args.index('--listen') + 1].removeprefix('unix://')
    data = {'argv': args, 'env': dict(os.environ), 'cwd': os.getcwd(), 'pid': os.getpid()}
    publish('fake-server', data)
    identity = ch / 'installation_id'
    if not identity.exists():
        identity.write_text('acme-' + uuid.uuid4().hex)
    database = ch / 'state_5.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE IF NOT EXISTS remote_control_enrollments '
                   '(environment_id TEXT, account_id TEXT)')
        if not db.execute('SELECT 1 FROM remote_control_enrollments').fetchone():
            db.execute('INSERT INTO remote_control_enrollments VALUES (?, ?)',
                       ('env_acme_' + uuid.uuid4().hex, 'acme-account'))
        environment = db.execute('SELECT environment_id FROM remote_control_enrollments').fetchone()[0]
    settings = {}
    for i, word in enumerate(args[:-1]):
        if word == '-c':
            key, _, value = args[i + 1].partition('=')
            try:
                value = tomllib.loads('value=' + value)['value']
            except tomllib.TOMLDecodeError:
                pass
            settings[key] = value

    def hook(event):
        if os.environ.get('FAKE_UNTRUSTED'):
            return
        for group in settings.get('hooks.' + event['hook_event_name'], []):
            for command in group['hooks']:
                subprocess.run(shlex.split(command['command']), input=json.dumps(event),
                               text=True, check=True)

    def rollout(sid, origin='user'):
        # its header, written before its start's hook runs, as 0.167's for a TUI's thread
        transcript = ch / 'sessions' / ('rollout-' + sid + '.jsonl')
        if not transcript.exists():
            transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {
                'id': sid, 'cwd': os.getcwd(), 'thread_source': origin, 'timestamp':
                    os.environ.get('FAKE_STAMP', '2026-09-11T08:00:00Z')}}) + '\n')
        return transcript

    def payload(sid, event, **fields):
        return {'session_id': sid, 'transcript_path': str(rollout(sid).resolve()),
                'cwd': os.getcwd(), 'hook_event_name': event, **fields}

    def said(sid, kind, part, text):      # a completed item, the owner's words or the model's
        with rollout(sid).open('a') as fh:
            item = {'type': 'item_completed', 'item': {'type': kind, 'content': [
                {'type': part, 'text': text}]}}
            fh.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
                                 'type': 'event_msg', 'payload': item}) + '\n')

    loaded = threading.Event()
    opened = {}     # each thread /new or /resume opened, by its start's source at its next prompt

    class Handler(socketserver.StreamRequestHandler):
        def send(self, message):
            self.wfile.write(frame(message))

        def handle(self):
            self.rfile.readline()
            headers = {}
            while (line := self.rfile.readline().strip()):
                key, _, value = line.decode().partition(':')
                headers[key.lower()] = value.strip()
            accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] +
                '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            self.wfile.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                             b'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
            monitor = False
            while msg := receive(self.rfile):
                if 'id' not in msg:
                    continue
                method, params = msg['method'], msg.get('params') or {}
                result = {}
                if method == 'remoteControl/status/read':
                    monitor = True
                    result = {'status': 'connected', 'environmentId': environment,
                              'serverName': 'acme-host', 'installationId': identity.read_text()}
                elif method == 'remoteControl/client/list':
                    result = {'data': [] if os.environ.get('FAKE_PAIRING') else [{'clientId': 'acme-phone'}]}
                elif method == 'remoteControl/pairing/start':
                    with (home / 'pairings.jsonl').open('a') as fh:
                        fh.write(json.dumps(params) + '\n')
                    result = {'manualPairingCode': 'ACME-1234', 'pairingCode': 'invented',
                              'environmentId': environment, 'expiresAt': 2000000000}
                elif method == 'thread/resume' and params.get('excludeTurns'):
                    transcript = ch / 'sessions' / ('rollout-' + params['threadId'] + '.jsonl')
                    if not transcript.exists() or (home / 'resume-blocked').exists():
                        self.send({'id': msg['id'], 'error': {'message': 'no rollout found'}})
                        publish('fake-resume-failed', params)
                        continue
                    self.send({'id': msg['id'], 'result': {'thread': {'id': params['threadId']}}})
                    publish('fake-subscribed', params)
                    previous = None
                    while not select.select([self.connection], [], [], .05)[0]:
                        notification = ch / 'settings-notification.json'
                        if notification.exists() and (current := notification.read_text()) != previous:
                            self.send(json.loads(current))
                            previous = current
                    return
                elif method in ('thread/start', 'thread/resume') and loaded.is_set():
                    sid = params.get('threadId') or str(uuid.uuid4())
                    rollout(sid)
                    opened[sid] = 'resume' if method.endswith('resume') else 'startup'
                    result = {'thread': {'id': sid}}
                elif method in ('thread/start', 'thread/resume'):
                    loaded.set()
                    sid = params.get('threadId') or os.environ['FAKE_THREAD']
                    event = payload(sid, 'SessionStart',
                                    source='resume' if method.endswith('resume') else 'startup')
                    hook(event)
                    hook({**event, 'hook_event_name': 'UserPromptSubmit', 'prompt': 'Ready?'})
                    state = home / '.agentkit/state' / ('hook-' + os.environ['AGENTKIT_SESSION'] + '.json')
                    if state.exists():
                        (ch / 'fake-working.json').write_text(state.read_text())
                    stop.update(event, hook_event_name='Stop', last_assistant_message='ACME_READY')
                    hook(stop)
                    result = {'thread': {'id': sid}}
                elif method == 'turn/start':
                    sid, words = params['threadId'], params['input'][0]['text']
                    if sid in opened:
                        hook(payload(sid, 'SessionStart', source=opened.pop(sid)))
                    hook(payload(sid, 'UserPromptSubmit', prompt=words))
                    said(sid, 'UserMessage', 'text', words)
                    said(sid, 'AgentMessage', 'Text', 'Done.')
                    hook(payload(sid, 'Stop', last_assistant_message='Done.'))
                elif method == 'fake/spawn':
                    # a sub-agent's thread: 0.167 fires no start for one, the fake fires one for a
                    # test to show it is not taken
                    sid = str(uuid.uuid4())
                    rollout(sid, 'subagent')
                    said(sid, 'UserMessage', 'text', params['prompt'])
                    hook(payload(sid, 'SessionStart', source='startup'))
                elif method in ('thread/backgroundTerminals/list', 'thread/list'):
                    # what the test says the thread runs in the background now, as the server
                    # lists it, ending with no `nextCursor`
                    listed = home / 'in-flight.json'
                    result = (json.loads(listed.read_text()) if listed.exists() else {}).get(
                        method, {'data': [], 'nextCursor': None})
                self.send({'id': msg['id'], 'result': result})
            if monitor:
                (ch / 'fake-monitor-closed').touch()

    # The thread's turn ends again on SIGUSR1, its Stop fired from this server as Codex fires it,
    # beside the loop that keeps serving.
    stop = {}
    signal.signal(signal.SIGUSR1, lambda signum, frame: threading.Thread(
        target=hook, args=(dict(stop),)).start())

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    if gate := os.environ.get('FAKE_STOP_GATE'):
        def stopped(signum, frame):
            Path(gate + '.waiting').touch()
            while not Path(gate).exists():
                time.sleep(.05)
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, stopped)
    server = Server(path, Handler)
    try:
        server.serve_forever(poll_interval=.05)
    finally:
        server.server_close()
else:
    assert '--remote' in args, args
    assert 'AGENTKIT_CODEX_RECEIPT' not in os.environ
    assert '--dangerously-bypass-hook-trust' not in args
    (home / 'last-command.json').write_text(json.dumps(args))
    if 'resume' in args and '--yolo' in args:    # Codex 0.160.1's own refusal
        print('Error: Permission overrides are not supported when resuming a remote task.',
              file=sys.stderr)
        sys.exit(1)
    # Its own client, not ak's: tests/test_go_keys.py runs this where agentkit/ is left out.
    # No timeout: the server answers once the thread's first turn has run its hooks, however
    # long a loaded host takes them.
    with socket.socket(socket.AF_UNIX) as client, client.makefile('rb') as wire:
        def send(message):
            client.sendall(frame(message, os.urandom(4)))
        client.connect(args[args.index('--remote') + 1].removeprefix('unix://'))
        key = base64.b64encode(os.urandom(16))
        client.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: '
                       b'Upgrade\r\nSec-WebSocket-Key: ' + key + b'\r\nSec-WebSocket-Version: 13'
                       b'\r\n\r\n')
        assert wire.readline().startswith(b'HTTP/1.1 101 ')
        while wire.readline().strip():
            pass
        send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'agentkit', 'version': '1'},
            'capabilities': {'experimentalApi': True}}})
        assert 'result' in receive(wire)
        send({'method': 'initialized'})
        method, params = (('thread/resume', {'threadId': args[args.index('resume') + 1]})
                          if 'resume' in args else ('thread/start', {}))
        send({'id': 0, 'method': method, 'params': params})
        sid = receive(wire)['result']['thread']['id']
        if os.environ.get('FAKE_SCREEN'):       # the screen a TUI at its prompt draws
            print(Path(os.environ['FAKE_SCREEN']).read_text(), end='', flush=True)
        publish('fake-tui', {'argv': args, 'pid': os.getpid()})
        while os.environ.get('FAKE_HOLD'):
            time.sleep(.05)
            # a TUI at its prompt takes each line typed into it, into fake-heard.jsonl with the
            # thread it went to: it names its thread on /rename where Codex keeps the names
            # (tests/fixtures/codex-title-index.jsonl), and its server takes the rest
            if os.environ.get('FAKE_SCREEN') and select.select([0], [], [], 0)[0]:
                for line in filter(str.strip, os.read(0, 4096).decode(errors='replace').splitlines()):
                    command, _, rest = line.partition(' ')
                    if command == '/rename':
                        with (ch / 'session_index.jsonl').open('a') as index:
                            index.write(json.dumps({'id': sid, 'thread_name': rest.strip(),
                                                    'updated_at': '2026-09-11T08:00:00Z'}) + '\n')
                    else:
                        method, params = {
                            '/new': ('thread/start', {}),
                            '/resume': ('thread/resume', {'threadId': rest.strip()}),
                            '/agent': ('fake/spawn', {'prompt': rest})}.get(command, (
                                'turn/start', {'threadId': sid,
                                               'input': [{'type': 'text', 'text': line}]}))
                        send({'id': 2, 'method': method, 'params': params})
                        sid = (receive(wire)['result'].get('thread') or {}).get('id', sid)
                    with (ch / 'fake-heard.jsonl').open('a') as heard:
                        heard.write(json.dumps([line, sid]) + '\n')
