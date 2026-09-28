"""Offline Codex stand-in: real Unix transport, invented conversations, no provider calls."""
import base64
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import signal
import socketserver
import struct
import subprocess
import sys
import time
import tomllib

args = sys.argv[1:]
home = Path.home()
repo = Path(os.environ['FAKE_CODEX_REPO'])
ch = Path(os.environ.get('CODEX_HOME', home / '.codex'))
if args == ['--help']:
    print('old CLI' if os.environ.get('FAKE_UNSUPPORTED') else '--dangerously-bypass-hook-trust')
    sys.exit(0)
if args[:1] == ['app-server']:
    assert '--remote-control' in args
    path = args[args.index('--listen') + 1].removeprefix('unix://')
    data = {'argv': args, 'env': dict(os.environ), 'cwd': os.getcwd(), 'pid': os.getpid()}
    (ch / 'fake-server.json').write_text(json.dumps(data))
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

    class Handler(socketserver.StreamRequestHandler):
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
            while first := self.rfile.read(2):
                size = first[1] & 127
                if size == 126:
                    size = struct.unpack('!H', self.rfile.read(2))[0]
                mask = self.rfile.read(4)
                msg = json.loads(bytes(v ^ mask[i % 4] for i, v in
                                       enumerate(self.rfile.read(size))))
                if 'id' not in msg:
                    continue
                method, params = msg['method'], msg.get('params') or {}
                result = {}
                if method == 'remoteControl/status/read':
                    result = {'status': 'connected', 'environmentId': 'env_acme_' + ch.name,
                              'serverName': 'acme-host', 'installationId': 'acme-installation'}
                elif method == 'remoteControl/client/list':
                    result = {'data': [] if os.environ.get('FAKE_PAIRING') else [{'clientId': 'acme-phone'}]}
                elif method == 'remoteControl/pairing/start':
                    with (home / 'pairings.jsonl').open('a') as fh:
                        fh.write(json.dumps(params) + '\n')
                    result = {'manualPairingCode': 'ACME-1234', 'pairingCode': 'invented',
                              'environmentId': 'env_acme_' + ch.name, 'expiresAt': 2000000000}
                elif method in ('thread/start', 'thread/resume'):
                    sid = params.get('threadId') or os.environ['FAKE_THREAD']
                    transcript = ch / 'sessions' / ('rollout-' + sid + '.jsonl')
                    if not transcript.exists():
                        transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {
                            'id': sid, 'cwd': os.getcwd(), 'timestamp': os.environ.get(
                                'FAKE_STAMP', '2026-09-11T08:00:00Z')}}) + '\n')
                    event = {'session_id': sid, 'transcript_path': str(transcript.resolve()),
                             'cwd': os.getcwd(), 'hook_event_name': 'SessionStart',
                             'source': 'resume' if method.endswith('resume') else 'startup'}
                    hook(event)
                    hook({**event, 'hook_event_name': 'UserPromptSubmit', 'prompt': 'Ready?'})
                    state = home / '.agentkit/state' / ('hook-' + os.environ['AGENTKIT_SESSION'] + '.json')
                    if state.exists():
                        (ch / 'fake-working.json').write_text(state.read_text())
                    hook({**event, 'hook_event_name': 'Stop', 'last_assistant_message': 'ACME_READY'})
                    result = {'thread': {'id': sid}}
                wire = json.dumps({'id': msg['id'], 'result': result}).encode()
                header = bytes([129, len(wire)]) if len(wire) < 126 else (
                    bytes([129, 126]) + struct.pack('!H', len(wire)))
                self.wfile.write(header + wire)

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
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
    Client = runpy.run_path(str(repo / 'tools/codex-seat.py'))['Client']
    client = Client(args[args.index('--remote') + 1].removeprefix('unix://'))
    try:
        if 'resume' in args:
            client.call('thread/resume', {'threadId': args[args.index('resume') + 1]})
        else:
            client.call('thread/start', {})
        (ch / 'fake-tui.json').write_text(json.dumps({'argv': args, 'pid': os.getpid()}))
        while os.environ.get('FAKE_HOLD'):
            time.sleep(.05)
    finally:
        client.close()
