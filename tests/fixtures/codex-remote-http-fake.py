"""sitecustomize for subprocess tests: remote enrollment requests never leave the fake HOME."""
import io
import json
import os
import sqlite3
from pathlib import Path
import urllib.error
import urllib.request


def urlopen(request, **kwargs):
    assert request.full_url.startswith('https://chatgpt.com/backend-api/wham/remote/control/environments/')
    assert request.get_header('Authorization') == 'Bearer acme-token'
    call = {'method': request.method, 'environment': request.full_url.rsplit('/', 1)[1],
            'body': json.loads(request.data) if request.data else None}
    with (Path.home() / 'remote-http.jsonl').open('a') as fh:
        fh.write(json.dumps(call) + '\n')
    if request.method == 'DELETE':
        for server in (Path.home() / '.agentkit/state').glob('codex-remote-*/fake-server.json'):
            with sqlite3.connect(server.parent / 'state_5.sqlite') as db:
                owned = db.execute('SELECT environment_id FROM remote_control_enrollments').fetchone()[0]
            if call['environment'] == owned:
                try:
                    os.kill(json.loads(server.read_text())['pid'], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError('deleted enrollment before stopping its server')
    if request.method == 'DELETE' and os.environ.get('FAKE_DELETE_BUSY'):
        marker = Path.home() / 'delete-busy'
        if not marker.exists():
            marker.touch()
            raise urllib.error.HTTPError(request.full_url, 409, 'online', {}, None)
    return io.BytesIO(b'{}')


urllib.request.urlopen = urlopen
