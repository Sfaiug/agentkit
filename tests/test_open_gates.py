"""The acceptance gates need nothing private and no privilege.

Both gates reuse a private remote under the caller's own account, reset to its seed before
each run, and the fresh gate runs in a throwaway HOME instead of a throwaway Unix account.
No fixed owner remains anywhere.
"""

from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config as akconfig, orch

SMOKE = (REPO / "tests/smoke.sh").read_text()
FRESH = (REPO / "tests/e2e-fresh.sh").read_text()


def owner():
    """The personal account name, built without writing it."""
    return "".join(chr(c) for c in (83, 102, 97, 105, 117, 103))


class OpenGates(unittest.TestCase):
    def setUp(self):
        # A fixture HOME must never borrow this test runner's overridden real logins.
        overrides = patch.dict(os.environ, {name: '' for name in
                               ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'XDG_CONFIG_HOME',
                                'XDG_DATA_HOME', 'GROK_HOME', 'GH_CONFIG_DIR',
                                'OPENCODE_CONFIG_DIR', 'OPENCODE_CONFIG')})
        overrides.start()
        self.addCleanup(overrides.stop)
        # Every harness binary a gate asks about is a fake, ahead of any this host installed:
        # smoke_home's login probe then runs each real adapter's `auth` against no real harness.
        fakes = tempfile.TemporaryDirectory(prefix=".open-gates-bin-", dir=REPO)
        self.addCleanup(fakes.cleanup)
        for name in ('claude', 'codex', 'muse', 'grok', 'opencode', 'agy'):
            (Path(fakes.name) / name).write_text('#!/bin/sh\nexit 97\n')
            (Path(fakes.name) / name).chmod(0o755)
        path = patch.dict(os.environ, {'PATH': f'{fakes.name}:{os.environ["PATH"]}'})
        path.start()
        self.addCleanup(path.stop)

    def test_smoke_links_only_credentials_never_caller_directories(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        credentials = ('.claude/.credentials.json', '.codex/auth.json',
                       '.config/muse/auth.json', '.grok/auth.json',
                       '.local/share/opencode/auth.json', '.config/gh/hosts.yml',
                       '.agentkit/secrets/claude_oauth_token', '.grok/auth.json.lock',
                       '.gemini/antigravity-cli/antigravity-oauth-token',
                       '.local/share/browser-bridge/Xauthority')
        copies = {'.claude.json': json.dumps({'oauthAccount': {'accountUuid': 'fixture'},
                                            'mcpServers': {'fixture': {'command': 'true'}}}),
                  '.gitconfig': '[user]\nname = fixture\n',
                  '.config/gh/config.yml': 'git_protocol: https\n',
                  '.config/opencode/opencode.json': '{"provider": {"mimo": {"apiKey": "fixture"}}}',
                  '.agentkit/secrets/discord_webhook': 'fixture webhook'}
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller, home = root / 'caller', root / 'work/home'
            for name in ('.claude', '.codex', '.config', '.grok', '.opencode',
                         '.local', '.npm-global'):
                (caller / name).mkdir(parents=True, exist_ok=True)
            for name, value in {**dict.fromkeys(credentials, 'fixture login'), **copies}.items():
                path = caller / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            result = subprocess.run(['bash', '-c', 'set -eu\n' + setup + '\nsmoke_home'],
                                    env={**os.environ, 'HOME': str(caller), 'REPO': str(REPO),
                                         'WORK': str(root / 'work')},
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            links = {str(path.relative_to(home)): path for path in home.rglob('*')
                     if path.is_symlink()}
            self.assertEqual(set(links), set(credentials))
            for name, path in links.items():
                self.assertTrue(path.is_file(), f'{name} links a directory')
                self.assertEqual(path.resolve(), caller / name)
            # Codex writes in place; the rename-based writers are exercised separately.
            links['.codex/auth.json'].write_text('refreshed login')
            self.assertEqual((caller / '.codex/auth.json').read_text(), 'refreshed login')
            for name, value in copies.items():
                self.assertEqual((home / name).read_text(), value)
                (home / name).write_text('sandbox edit')
                self.assertEqual((caller / name).read_text(), value)
            # A login the caller has that cannot be read, itself or through its link, ends the
            # suite, and so does one the sandbox cannot take: never an absence.
            (root / 'vault').mkdir()
            (caller / '.config/muse/auth.json').rename(root / 'vault/auth.json')
            (caller / '.config/muse/auth.json').symlink_to(root / 'vault/auth.json')
            for broken, said in ((caller / '.codex/auth.json', f'cannot read {caller}/.codex/auth.json'),
                                 (caller / '.codex', f'cannot read {caller}/.codex/auth.json'),
                                 (root / 'vault', f'cannot read {caller}/.config/muse/auth.json'),
                                 (home / '.codex', 'mkdir'), (home / '.claude.json', 'cp')):
                with self.subTest(broken=broken.name):
                    shutil.rmtree(home)
                    if broken.is_relative_to(home):   # a file for a directory, a link to nowhere
                        home.mkdir()
                        broken.touch() if said == 'mkdir' else broken.symlink_to(root / 'gone/x')
                    else:
                        broken.chmod(0)
                    result = subprocess.run(['bash', '-c', setup + '\nsmoke_home'],
                                            env={**os.environ, 'HOME': str(caller),
                                                 'REPO': str(REPO), 'WORK': str(root / 'work')},
                                            text=True, capture_output=True, timeout=10)
                    if not broken.is_relative_to(home):
                        broken.chmod(0o700)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(said, result.stderr)
            # A login whose missing directory sits directly under `/`, as CODEX_HOME=/codex, is
            # absent, just as one under a missing directory in /tmp is.
            missing = f'/.open-gates-{os.getpid()}'
            self.assertFalse(os.path.lexists(missing))
            shutil.rmtree(home)
            result = subprocess.run(['bash', '-c', setup + '\nsmoke_home'],
                                    env={**os.environ, 'HOME': str(caller), 'CODEX_HOME': missing,
                                         'REPO': str(REPO), 'WORK': str(root / 'work')},
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(os.path.lexists(home / '.codex/auth.json'))

    def test_smoke_counts_only_logins_its_adapters_confirm(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        # A lapsed Grok key its refresh token renews: the real adapter's yes on the linked login.
        login = {'id': {'key': 'k', 'expires_at': '2000-01-01T00:00:00Z', 'refresh_token': 'r'}}
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller, home, binaries, adapters = (root / 'caller', root / 'work/home',
                                                root / 'bin', root / 'adapters')
            (caller / '.grok').mkdir(parents=True)
            (caller / '.grok/auth.json').write_text(json.dumps(login))
            # OpenCode's settings with no key in them, and nothing in its auth store, are no login.
            (caller / '.config/opencode').mkdir(parents=True)
            (caller / '.config/opencode/opencode.json').write_text('{"theme": "dark"}')
            binaries.mkdir()
            adapters.mkdir()
            for name in ('grok', 'codex', 'claude', 'muse', 'opencode'):
                (binaries / name).write_text('#!/bin/sh\nexit 97\n')
                (binaries / name).chmod(0o755)
            # An answer with no line, no answer at all, or none within worker.auth_ok's bound
            # confirms nothing.
            for harness, body in (('grokbuild', f'exec {REPO}/adapters/grokbuild.sh "$@"'),
                                  ('opencode', f'exec {REPO}/adapters/opencode.sh "$@"'),
                                  ('codex', 'exit 0'), ('claude', 'echo fixture; exit 2'),
                                  ('muse', 'exec sleep 60'),
                                  ('antigravity', 'exit 1')):
                (adapters / f'{harness}.sh').write_text(f'#!/bin/bash\n{body}\n')
                (adapters / f'{harness}.sh').chmod(0o755)
            script = ('set -eu\n' + setup + '\nsmoke_home\n'
                      'printf "SMOKE_LOGINS=[%s]\\n" "$SMOKE_LOGINS"\n')
            env = {name: value for name, value in os.environ.items()
                   if name not in ('XAI_API_KEY', 'GROK_HOME')}
            result = subprocess.run(['bash', '-c', script],
                                    env={**env, 'HOME': str(caller), 'REPO': str(REPO),
                                         'WORK': str(root / 'work'),
                                         'PATH': f'{binaries}:/usr/bin:/bin',
                                         'AGENTKIT_ADAPTER_DIR': str(adapters)},
                                    text=True, capture_output=True, timeout=50)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('SMOKE_LOGINS=[grokbuild]', result.stdout)
            self.assertEqual((home / '.grok/auth.json').resolve(), caller / '.grok/auth.json')

    def test_gates_merge_back_only_valid_renamed_logins_whole(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        sync_back = FRESH[FRESH.index('sync_back() {'):FRESH.index('\ncleanup_logs()')]
        old = {'claudeAiOauth': {'accessToken': 'old', 'refreshToken': 'old-pair',
                                'expiresAt': 4_000_000_000_000}}
        fresh = {'claudeAiOauth': {'accessToken': 'new', 'refreshToken': 'new-pair',
                                  'expiresAt': 4_100_000_000_000}}
        grok_old = {'fixture': {'key': 'old', 'expires_at': '2096-01-01T00:00:00Z'}}
        grok_fresh = {'fixture': {'key': 'new', 'expires_at': '2099-01-01T00:00:00Z'}}
        # What Claude and Grok do on a refresh: a new file renamed over the link.
        rename = '''python3 - <<'PY'
import os
from pathlib import Path
path = Path(os.environ['SANDBOX']) / os.environ['LOGIN_PATH']
assert path.is_symlink()
tmp = path.with_suffix('.tmp')
tmp.write_text(os.environ['REPLACEMENT'])
tmp.replace(path)
assert not path.is_symlink()
PY
'''
        # The smoke suite's own borrowing, and a link as the e2e gate lends it, each with its
        # own merge-back.
        gates = {'smoke': ('set -eu\n' + setup + '\nsmoke_home\nexport SANDBOX=$HOME\n' + rename
                           + 'smoke_sync_logins\n'),
                 'e2e': ('set -eu\nsay() { :; }\n' + sync_back
                         + '\nexport SANDBOX="$WORK/home"\nUH=$SANDBOX INVOKER=fixture\n'
                         'caller_claude="$HOME/.claude" caller_grok="$HOME/.grok"\n'
                         'mkdir -p -- "$(dirname -- "$UH/$LOGIN_PATH")"\n'
                         'ln -s -- "$HOME/$LOGIN_PATH" "$UH/$LOGIN_PATH"\n' + rename + 'sync_back\n')}
        for relative, original, replacement in (('.claude/.credentials.json', old, fresh),
                                                 ('.grok/auth.json', grok_old, grok_fresh)):
            for gate, content, expected, behind_link in (
                    ('smoke', replacement, replacement, False),
                    ('e2e', replacement, replacement, False),
                    ('smoke', replacement, replacement, True),
                    ('smoke', {}, original, False),
                    ('smoke', {key: {} for key in original}, original, False),
                    ('smoke', {key: {**value, 'expiresAt': 1, 'expires_at': '2000-01-01T00:00:00Z'}
                               for key, value in replacement.items()}, original, False),
                    ('smoke', original, original, False),
                    ('smoke', 'invalid JSON', original, False)):
                with self.subTest(path=relative, gate=gate, replacement=content, link=behind_link), \
                        tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
                    root = Path(tmp)
                    path = root / 'caller' / relative
                    path.parent.mkdir(parents=True)
                    # The caller's own login may itself be a link, into dotfiles say.
                    target = root / 'dotfiles/login.json' if behind_link else path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(original))
                    target.chmod(0o600)
                    if behind_link:
                        path.symlink_to(target)
                    before = target.stat()
                    result = subprocess.run(['bash', '-c', gates[gate]],
                                            env={**os.environ, 'HOME': str(root / 'caller'),
                                                 'REPO': str(REPO), 'WORK': str(root / 'work'),
                                                 'LOGIN_PATH': relative,
                                                 'REPLACEMENT': content if isinstance(content, str)
                                                 else json.dumps(content)},
                                            text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(json.loads(path.read_text()), expected)
                    self.assertEqual(path.is_symlink(), behind_link)
                    self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                    if expected == original:
                        self.assertEqual((target.stat().st_ino, target.stat().st_mtime_ns),
                                         (before.st_ino, before.st_mtime_ns))
                    else:   # written beside it and renamed over, never truncated in place
                        self.assertNotEqual(target.stat().st_ino, before.st_ino)
                    self.assertEqual([name for name in os.listdir(target.parent)
                                      if name.startswith(f'.{target.name}.')], [])
        self.assertIn('WORK="$STREAM_HOME" smoke_sync_logins', SMOKE)
        cleanup = SMOKE[SMOKE.index("trap 'SMOKE_RC=$?"):SMOKE.index('# --- the suite\'s own tmux')]
        self.assertLess(cleanup.index('smoke_sync_logins'), cleanup.index('retention settle'))
        cleanup = FRESH[FRESH.index('cleanup() {'):FRESH.index('\ntrap cleanup EXIT')]
        self.assertLess(cleanup.index('sync_back'), cleanup.index('cleanup_logs'))

    def test_smoke_borrows_overridden_logins_before_clearing_overrides(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller, home = root / 'caller', root / 'work/home'
            caller.mkdir()
            overrides = {name: str(root / name.lower()) for name in
                         ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'XDG_CONFIG_HOME',
                          'XDG_DATA_HOME', 'GROK_HOME', 'GH_CONFIG_DIR', 'OPENCODE_CONFIG_DIR')}
            sources = {'.claude/.credentials.json': ('CLAUDE_CONFIG_DIR', '.credentials.json'),
                       '.codex/auth.json': ('CODEX_HOME', 'auth.json'),
                       '.config/muse/auth.json': ('XDG_CONFIG_HOME', 'muse/auth.json'),
                       '.grok/auth.json': ('GROK_HOME', 'auth.json'),
                       '.local/share/opencode/auth.json': ('XDG_DATA_HOME', 'opencode/auth.json'),
                       '.config/gh/hosts.yml': ('GH_CONFIG_DIR', 'hosts.yml'),
                       '.claude.json': ('CLAUDE_CONFIG_DIR', '.claude.json'),
                       '.config/gh/config.yml': ('GH_CONFIG_DIR', 'config.yml'),
                       '.config/opencode/opencode.json': ('OPENCODE_CONFIG_DIR', 'opencode.json')}
            for name, (override, relative) in sources.items():
                path = Path(overrides[override]) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'source': name}))
            result = subprocess.run(['bash', '-c', 'set -eu\n' + setup + '''
smoke_home
python3 - <<'PY'
import os
for name in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME',
             'GROK_HOME', 'GH_CONFIG_DIR', 'OPENCODE_CONFIG_DIR'):
    assert name not in os.environ, name
PY
'''], env={**os.environ, **overrides, 'HOME': str(caller), 'REPO': str(REPO),
           'WORK': str(root / 'work')}, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name, (override, relative) in sources.items():
                self.assertEqual(json.loads((home / name).read_text()), {'source': name})
                if name.endswith(('auth.json', 'hosts.yml', '.credentials.json')):
                    self.assertEqual((home / name).resolve(), Path(overrides[override]) / relative)
            self.assertEqual((home / '.grok/auth.json.lock').resolve(),
                             Path(overrides['GROK_HOME']) / 'auth.json.lock')
            with open(Path(overrides['GROK_HOME']) / 'auth.json.lock', 'w') as caller_lock, \
                    open(home / '.grok/auth.json.lock', 'a') as sandbox_lock:
                fcntl.flock(caller_lock, fcntl.LOCK_EX)
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(sandbox_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_smoke_mcp_claude_uses_worker_token_instead_of_refreshing_seat(self):
        block = SMOKE[SMOKE.index('  BP=\'Use the browser MCP'):SMOKE.index('  if skip_spent 31e')]
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            home = Path(tmp)
            (home / '.agentkit/secrets').mkdir(parents=True)
            (home / '.agentkit/secrets/claude_oauth_token').write_text('worker-token')
            (home / '.claude').mkdir()
            caller = home / 'caller-login'
            caller.write_text('seat login')
            (home / '.claude/.credentials.json').symlink_to(caller)
            result = subprocess.run(['bash', '-c', '''set -eu
ok() { :; }
no() { echo "$*" >&2; exit 1; }
claude() {
  python3 - <<'PY'
import os
from pathlib import Path
path = Path.home() / '.claude/.credentials.json'
if os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') != 'worker-token':
    tmp = path.with_suffix('.tmp')
    tmp.write_text('{}')
    tmp.replace(path)
    raise SystemExit('seat login would have been refreshed')
print('BROWSER_TABS=1 DESKTOP=ok')
PY
}
if false; then :; else
''' + block], env={**os.environ, 'HOME': tmp, 'WORK': tmp, 'REPO': str(REPO),
                  'CLAUDE_CODE_OAUTH_TOKEN': ''}, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((home / '.claude/.credentials.json').is_symlink())
            self.assertEqual(caller.read_text(), 'seat login')

    def test_smoke_install_and_hooks_leave_caller_contents_and_mtimes_untouched(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller, home, binaries = root / 'caller', root / 'work/home', root / 'bin'
            files = {'.claude/settings.json': '{"hooks": {}, "caller": true}\n',
                     '.grok/hooks/agentkit.json': '{"hooks": {}, "caller": true}\n',
                     '.claude.json': '{"oauthAccount": {}, "projects": {"caller": {}}}\n',
                     '.codex/config.toml': '[projects.caller]\ntrust_level = "trusted"\n',
                     '.config/muse/settings.json': '{}\n',
                     '.config/opencode/opencode.json': '{}\n',
                     '.local/share/opencode/cache': 'caller cache',
                     '.local/share/browser-bridge/Xauthority': 'fixture display credential',
                     '.opencode/bin/opencode': 'caller binary',
                     '.npm-global/bin/codex': 'caller binary',
                     '.local/bin/old-ak': 'caller binary',
                     '.gitconfig': '[user]\nname = fixture\n',
                     '.agentkit/secrets/discord_webhook': 'fixture webhook'}
            for name in ('.claude/.credentials.json', '.codex/auth.json',
                         '.config/muse/auth.json', '.grok/auth.json',
                         '.local/share/opencode/auth.json', '.config/gh/hosts.yml'):
                files[name] = '{}\n'
            for name, content in files.items():
                path = caller / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                os.utime(path, ns=(1_000_000_000, 1_000_000_000))
            (caller / '.local/bin/ak').symlink_to('old-ak')
            binaries.mkdir()
            # Real installers and hooks, but no real harness, tmux server or npx download.
            for name in ('claude', 'codex', 'muse', 'grok', 'opencode', 'tmux', 'npx'):
                path = binaries / name
                path.write_text('#!/bin/bash\nexit 1\n')
                path.chmod(0o755)

            def snapshot():
                return {str(path.relative_to(caller)):
                        (path.lstat().st_mtime_ns,
                         os.readlink(path) if path.is_symlink() else
                         path.read_bytes() if path.is_file() else None)
                        for path in [caller, *caller.rglob('*')]}

            before = snapshot()
            result = subprocess.run(['bash', '-c', 'set -eu\n' + setup + '''
smoke_home
bash "$REPO/install.sh" --server
"$REPO/adapters/claude.sh" hooks
"$REPO/adapters/grokbuild.sh" hooks
git config --global user.name sandbox
'''], env={**os.environ, 'HOME': str(caller), 'REPO': str(REPO),
           'WORK': str(root / 'work'), 'GROK_HOME': str(caller / '.grok'),
           'XDG_CONFIG_HOME': str(caller / '.config'), 'CODEX_HOME': str(caller / '.codex'),
           'PATH': f'{binaries}:{REPO / "bin"}:{os.environ["PATH"]}',
           'PYTHONDONTWRITEBYTECODE': '1'}, stdin=subprocess.DEVNULL,
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(snapshot(), before)
            for name in ('.claude/settings.json', '.grok/hooks/agentkit.json'):
                self.assertIn(str(REPO / 'hooks/seat-state.sh'), (home / name).read_text())
                self.assertFalse((home / name).is_symlink())
            self.assertEqual((home / '.local/bin/ak').resolve(), REPO / 'bin/ak')
            codex = tomllib.loads((home / '.codex/config.toml').read_text())
            self.assertEqual(set(codex['mcp_servers']), {'browser', 'desktop'})
            self.assertNotIn('projects', codex)
            claude = json.loads((home / '.claude.json').read_text())
            for server in (codex['mcp_servers']['desktop'], claude['mcpServers']['desktop']):
                authority = Path(server['env']['XAUTHORITY'])
                self.assertEqual(authority.read_text(), 'fixture display credential')
                self.assertEqual(authority.resolve(), caller / '.local/share/browser-bridge/Xauthority')

    def test_smoke_never_reads_callers_config(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        flags = SMOKE[SMOKE.index('codex_model_flag_check()'):SMOKE.index('# Fake-adapter loops:')]
        shipped = (REPO / 'config.default.toml').read_text()
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller = root / 'caller'
            (caller / '.agentkit/secrets').mkdir(parents=True)
            (caller / '.agentkit/secrets/claude_oauth_token').write_text('fixture worker token')
            (caller / '.agentkit/state').mkdir()
            meter = {'fetched_at': 100, 'meters': []}
            for name in ('usage-meta.json', 'usage-meta-probe.json', 'usage.json'):
                (caller / '.agentkit/state' / name).write_text(json.dumps(meter))
            fixture = root / 'repo'
            fixture.mkdir()
            for name in ('agentkit', 'adapters', 'tools', 'hooks'):
                (fixture / name).symlink_to(REPO / name)
            (fixture / 'config.default.toml').write_text(shipped)
            # Every Python in the extracted checks refuses even an attempted caller read.
            (fixture / 'sitecustomize.py').write_text('''import os, sys
def guard(event, args):
    if event == 'open' and args[0] == os.environ['FORBIDDEN_CONFIG']:
        raise AssertionError('smoke read the caller config')
sys.addaudithook(guard)
''')
            config_path = caller / '.agentkit/config.toml'
            for index, content in enumerate((shipped.replace('model = "default"', 'model = "pinned"')
                                             .replace('workers = ["opus", "astra"]',
                                                      'workers = ["astra"]'), 'not valid TOML')):
                with self.subTest(config=content[:30]):
                    config_path.write_text(content)
                    work = root / f'work-{index}'
                    env = {**os.environ, 'HOME': str(caller), 'REPO': str(fixture),
                           'WORK': str(work), 'TMPDIR': tmp,
                           'FORBIDDEN_CONFIG': str(config_path), 'PYTHONDONTWRITEBYTECODE': '1'}
                    result = subprocess.run(['bash', '-c', 'set -eu\n' + setup + flags + '''
codex_model_flag_check
smoke_home
PYTHONPATH="$REPO" python3 - <<'PY'
import os, pathlib, tomllib
from agentkit import config
assert config.HOME == pathlib.Path(os.environ['WORK']) / 'home/.agentkit'
with open(pathlib.Path(os.environ['REPO']) / 'config.default.toml', 'rb') as fh:
    shipped = tomllib.load(fh)
cfg = config.load()
assert cfg['defaults'] == shipped['defaults']
assert cfg['models']['astra'] == shipped['models']['astra']
PY
'''], env=env, text=True, capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(config_path.read_text(), content)
                    self.assertEqual((work / 'home/.agentkit/config.toml').read_text(), shipped)
                    self.assertEqual((work / 'home/.agentkit/secrets/claude_oauth_token').resolve(),
                                     caller / '.agentkit/secrets/claude_oauth_token')
                    for name in ('usage-meta.json', 'usage-meta-probe.json'):
                        copied = work / 'home/.agentkit/state' / name
                        self.assertEqual(json.loads(copied.read_text()), meter)
                        self.assertFalse(copied.is_symlink())
                    self.assertFalse((work / 'home/.agentkit/state/usage.json').exists())
        main = SMOKE[SMOKE.index('WORK="$HOME/.agentkit/tmp/smoke-'):]
        self.assertLess(main.index('\nsmoke_home\n'), main.index('echo "workdir:'))

    def test_smoke_seat_expected_row_comes_from_shipped_defaults(self):
        start = SMOKE.index('SEATWANT=')
        check = SMOKE[start:SMOKE.index('SEATENV=', start)]
        shipped = (REPO / 'config.default.toml').read_text()
        defaults = tomllib.loads(shipped)['defaults']['workers']
        every = list(tomllib.loads(shipped)['models'])
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            for workers in (defaults, list(reversed(defaults)), ['astra'], every):
                with self.subTest(workers=workers):
                    config = shipped.replace('workers = ' + str(defaults).replace("'", '"'),
                                             'workers = ' + str(workers).replace("'", '"'))
                    (root / 'config.default.toml').write_text(config)
                    for shown in (workers, workers + ['extra'], workers[:-1], list(reversed(workers))):
                        with patch.object(akconfig, 'STATE', root), \
                                patch.object(orch, 'state_word', return_value='needs you'), \
                                patch.object(orch.time, 'time', return_value=1000):
                            _, rows = orch.list_table(
                                [{'name': 'smoke-astra', 'repo': None, 'created': 940}],
                                tomllib.loads(config), {}, 100,
                                {'smoke-astra': {'orchestrator': 'astra', 'workers': shown}})
                        row = '\n'.join(rows[0])
                        if workers == every and shown == workers:
                            self.assertRegex(row, r'grok,.*\n {20,}gemini,mimo')
                        result = subprocess.run(['bash', '-c', '''set -uo pipefail
ak() { printf '%s\\n' "$ROW"; }
''' + check + '\nprintf "%s\\n" "$SEATLIST"'],
                                                env={**os.environ, 'REPO': tmp, 'ROW': row},
                                                text=True, capture_output=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), '1' if shown == workers else '0')

    def test_smoke_skips_missing_harness_or_login_with_reason(self):
        start = SMOKE.index('model_unavailable()')
        helpers = SMOKE[start:SMOKE.index('U="$WORK/usage.json"', start)]
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            binaries = root / 'bin'
            binaries.mkdir()
            (binaries / 'python3').symlink_to(sys.executable)
            adapter = binaries / 'codex.sh'
            adapter.write_text('#!/bin/bash\nprintf "%s\\n" "${AUTH_WHY:-codex: no $HOME/.codex/auth.json; run codex login}"\nexit "${AUTH_RC:-1}"\n')
            adapter.chmod(0o755)
            env = {**os.environ, 'HOME': tmp, 'WORK': tmp, 'REPO': str(REPO),
                   'PATH': str(binaries), 'AGENTKIT_ADAPTER_DIR': str(binaries)}
            for installed, auth_rc, reason in ((False, '0', 'codex is not installed'),
                                                (True, '1', 'run codex login'),
                                                (True, '0', ''), (True, '2', '')):
                with self.subTest(installed=installed, auth=auth_rc):
                    if installed:
                        (binaries / 'codex').touch(mode=0o755)
                    result = subprocess.run(['/bin/bash', '-c',
                                             '. "$REPO/tests/acceptance.sh"\n' + helpers
                                             + '\nskip_unavailable 3a/3b astra || :\n'],
                                            env={**env, 'AUTH_RC': auth_rc},
                                            text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if reason:
                        self.assertEqual(result.stdout.count('SKIP '), 2)
                        self.assertIn(reason, result.stdout)
                    else:
                        self.assertEqual(result.stdout, '')
            (root / '.codex').mkdir()
            for why in ('codex: no ' + str(root / '.codex/auth.json') + '; run codex login',
                        'codex: the token expired; run codex login',
                        'codex: the expiry cannot be read; run codex login'):
                with self.subTest(broken=why):
                    (root / '.codex/auth.json').write_text('broken credential')
                    result = subprocess.run(['/bin/bash', '-c',
                                             '. "$REPO/tests/acceptance.sh"\n' + helpers
                                             + '\nskip_unavailable 3a/3b astra\nfinish'],
                                            env={**env, 'AUTH_RC': '1', 'AUTH_WHY': why},
                                            text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('login check failed: ' + why, result.stdout)
                    self.assertNotIn('SKIP ', result.stdout)

    def test_smoke_needs_one_harness_with_its_login(self):
        # None of the three check 3 calls is here: each skips by name, as not on this host,
        # and the suite still fails, because it made no real call at all.
        start = SMOKE.index('model_unavailable()')
        helpers = SMOKE[start:SMOKE.index('U="$WORK/usage.json"', start)]
        check = SMOKE[SMOKE.index('# --- 3:'):SMOKE.index('# --- 4:')]
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            binaries = Path(tmp) / 'bin'
            binaries.mkdir()
            (binaries / 'python3').symlink_to(sys.executable)
            result = subprocess.run(['/bin/bash', '-c', '. "$REPO/tests/acceptance.sh"\n'
                                     'ak() { return 1; }\n' + helpers + check + '\nfinish'],
                                    env={**os.environ, 'HOME': tmp, 'WORK': tmp,
                                         'REPO': str(REPO), 'PATH': str(binaries),
                                         'AGENTKIT_ADAPTER_DIR': ''},
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for model, harness in (('opus', 'claude'), ('astra', 'codex'), ('spark', 'muse')):
            self.assertIn(f'SKIP  3b: required model {model} is not on this host: '
                          f'{harness} is not installed', result.stdout)
        self.assertIn('FAIL  3: no harness here is installed with its login', result.stdout)
        self.assertIn('6 passed, 1 failed, 0 skipped', result.stdout)
        # A login smoke_home's adapters confirmed is that one harness, called here or not.
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            binaries = Path(tmp) / 'bin'
            binaries.mkdir()
            (binaries / 'python3').symlink_to(sys.executable)
            result = subprocess.run(['/bin/bash', '-c', '. "$REPO/tests/acceptance.sh"\n'
                                     'ak() { return 1; }\nSMOKE_LOGINS=" grokbuild"\n'
                                     + helpers + check + '\nfinish'],
                                    env={**os.environ, 'HOME': tmp, 'WORK': tmp,
                                         'REPO': str(REPO), 'PATH': str(binaries),
                                         'AGENTKIT_ADAPTER_DIR': ''},
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('6 passed, 0 failed, 0 skipped', result.stdout)

    def test_fresh_borrows_what_this_host_has_and_needs_one_harness(self):
        callers = FRESH[FRESH.index('caller_config=${XDG_CONFIG_HOME'):FRESH.index('\nTS=$(date')]
        block = FRESH[FRESH.index('  # Each login is linked, file by file'):
                      FRESH.index('  # `claude` also writes')]

        def gate(hostbin, logins, answers, broken=()):
            """Step c's borrowing, with each adapter's `auth` answering "<exit> <line>"."""
            with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
                root = Path(tmp)
                caller, home, fixtures = root / 'caller', root / 'home', root / 'answers'
                (home / 'agentkit/adapters').mkdir(parents=True)
                (home / 'agentkit/agentkit').symlink_to(REPO / 'agentkit')
                fixtures.mkdir()
                # The adapter reads its answer; `hang` is one that never comes.
                adapter = (f'#!/bin/sh\n[ "$1" = auth ] || exit 97\n'
                           f'read -r rc line <"{fixtures}/$(basename "$0" .sh)" || exit 98\n'
                           f'[ "$rc" != hang ] || exec sleep 60\n'
                           f'[ -z "$line" ] || echo "$line"; exit "$rc"\n')
                for harness in ('claude', 'codex', 'muse', 'grokbuild', 'opencode',
                                'antigravity'):
                    (home / f'agentkit/adapters/{harness}.sh').write_text(adapter)
                    (home / f'agentkit/adapters/{harness}.sh').chmod(0o755)
                for name, answer in answers.items():
                    (fixtures / name).write_text(answer + '\n')
                for name, value in logins.items():
                    (caller / name).parent.mkdir(parents=True, exist_ok=True)
                    (caller / name).write_text(value)
                for side, name in broken:   # a login there but unreadable, or a HOME that cannot take it
                    if side == 'link':   # a login linked into a directory that cannot be searched
                        (root / 'vault').mkdir()
                        (caller / name).rename(root / 'vault/login')
                        (caller / name).symlink_to(root / 'vault/login')
                        (root / 'vault').chmod(0)
                    else:
                        (caller / name).chmod(0) if side == 'caller' else (home / name).touch()
                script = ('. "$REPO/tests/acceptance.sh"\nbad=""\n' + callers + '\n' + block
                          + 'printf "HERE=%s\\nSEAT=%s\\nbad=%s\\n" "$HERE" "$SEATLOGIN" "$bad"\n'
                          'finish')
                result = subprocess.run(['/bin/bash', '-c', script],
                                        env={**os.environ, 'WORK': tmp, 'REPO': str(REPO),
                                             'INVHOME': str(caller), 'UH': str(home),
                                             'HOSTBIN': f' {hostbin} ', 'EPATH': '/usr/bin:/bin',
                                             'AGENTKIT_ACCEPTANCE_REQUIRED': '1'},
                                        text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                lent = [path for path in home.rglob('*') if path.parts[len(home.parts)] != 'agentkit']
                links = {str(path.relative_to(home)): path.resolve()
                         for path in lent if path.is_symlink()}
                copies = {str(path.relative_to(home)): path.read_text()
                          for path in lent if path.is_file() and not path.is_symlink()}
                return result.stdout, links, copies, caller

        # A Claude host logged in by its worker token alone: that is a login, but no seat of
        # its own, so the menu step is skipped; every other harness and secret is skipped.
        out, links, _, caller = gate('claude',
                                     {'.agentkit/secrets/claude_oauth_token': 'fixture token'},
                                     {'claude': '0 fixture: worker token'})
        self.assertIn('HERE= claude:anthropic\nSEAT=\nbad=\n', out)
        for absent in ('codex', 'muse', 'grokbuild', 'opencode', 'antigravity'):
            self.assertIn(f'SKIP  c: {absent} is not on this host', out)
        self.assertIn('SKIP  c: the Discord webhook is not on this host', out)
        self.assertIn('SKIP  c: the Discord user id is not on this host', out)
        self.assertEqual(links, {'.agentkit/secrets/claude_oauth_token':
                                 caller / '.agentkit/secrets/claude_oauth_token'})
        # So is a Codex login whose missing directory sits directly under `/`, as CODEX_HOME=/codex.
        missing = f'/.open-gates-{os.getpid()}'
        self.assertFalse(os.path.lexists(missing))
        with patch.dict(os.environ, {'CODEX_HOME': missing}):
            out, _, _, _ = gate('claude', {'.agentkit/secrets/claude_oauth_token': 'fixture token'},
                                {'claude': '0 fixture: worker token'})
        self.assertIn('HERE= claude:anthropic\nSEAT=\nbad=\n', out)
        self.assertIn('SKIP  c: codex is not on this host', out)
        # A seat pair that is there, whatever it holds, is the menu step's to judge, not a skip.
        out, _, _, _ = gate('claude', {'.agentkit/secrets/claude_oauth_token': 'fixture token',
                                       '.claude/.credentials.json': 'not JSON'},
                            {'claude': '0 fixture: worker token'})
        self.assertIn('HERE= claude:anthropic\nSEAT=1\nbad=\n', out)
        # A Grok-only host lends its login and its lock, both linked, so Grok renews the
        # caller's own login under the caller's own lock.
        out, links, _, caller = gate('grok', {'.grok/auth.json': '{}'},
                                     {'grokbuild': '0 grok: renews its lapsed key itself'})
        self.assertIn('HERE= grokbuild:-\nSEAT=\nbad=\n', out)
        self.assertEqual(links, {'.grok/auth.json': caller / '.grok/auth.json',
                                 '.grok/auth.json.lock': caller / '.grok/auth.json.lock'})
        # OpenCode's settings with no key in them lend no login: its refusal is a skip, and the
        # settings, like the Discord secret, are a copy.
        out, links, copies, _ = gate('claude opencode',
                                     {'.agentkit/secrets/claude_oauth_token': 'fixture token',
                                      '.config/opencode/opencode.json': '{"theme": "dark"}',
                                      '.agentkit/secrets/discord_webhook': 'fixture webhook'},
                                     {'claude': '0 fixture: worker token',
                                      'opencode': '1 opencode: no provider key; run opencode auth login'})
        self.assertIn('HERE= claude:anthropic\nSEAT=\nbad=\n', out)
        self.assertIn("SKIP  c: opencode's login is not on this host: opencode: no provider key", out)
        self.assertEqual(set(links), {'.agentkit/secrets/claude_oauth_token'})
        self.assertEqual(copies, {'.config/opencode/opencode.json': '{"theme": "dark"}',
                                  '.agentkit/secrets/discord_webhook': 'fixture webhook'})
        # A login this host lent that is refused, unanswered in time, unreadable or cannot be
        # linked fails, for every harness; no harness at all fails.
        for host, logins, answers, broken, why in (
                ('codex', {'.codex/auth.json': '{}'}, {'codex': '1 codex: the token expired'},
                 (), 'bad=; codex: the token expired'),
                ('grok', {'.grok/auth.json': '{}'}, {'grokbuild': '1 grok: the login is expired'},
                 (), 'bad=; grok: the login is expired'),
                ('codex', {'.codex/auth.json': '{}'}, {'codex': '2 codex: jq is missing'},
                 (), 'bad=; codex: its auth gave no answer: codex: jq is missing'),
                ('codex', {'.codex/auth.json': '{}'}, {'codex': 'hang'},
                 (), 'bad=; codex: its auth gave no answer: ; no harness here'),
                ('codex', {'.codex/auth.json': '{}'}, {'codex': '0'},
                 (), 'bad=; codex: its auth gave no answer: ; no harness here'),
                ('codex', {'.codex/auth.json': '{}'}, {'codex': '0 codex: fine'},
                 (('caller', '.codex/auth.json'),), '/.codex/auth.json cannot be read'),
                ('codex', {'.codex/auth.json': '{}'}, {'codex': '0 codex: fine'},
                 (('caller', '.codex'),), '/.codex/auth.json cannot be read'),
                ('codex', {'.codex/auth.json': '{}'}, {'codex': '0 codex: fine'},
                 (('link', '.codex/auth.json'),), '/.codex/auth.json cannot be read'),
                ('codex', {'.codex/auth.json': '{}'}, {'codex': '0 codex: fine'},
                 (('home', '.codex'),), 'auth.json could not be linked into the new HOME'),
                ('', {}, {}, (), 'bad=; no harness here is installed with its login; the gate needs one')):
            with self.subTest(why=why, broken=broken):
                out, _, _, _ = gate(host, logins, answers, broken)
                self.assertIn(why, out)

    def test_smoke_finds_installer_binaries_without_login_shell_path(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        start = SMOKE.index('model_unavailable()')
        helpers = SMOKE[start:SMOKE.index('U="$WORK/usage.json"', start)]
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller, binaries, adapters = root / 'caller', root / 'bin', root / 'adapters'
            binaries.mkdir()
            adapters.mkdir()
            for name in ('python3', 'mkdir', 'cp', 'ln'):
                (binaries / name).symlink_to(shutil.which(name))
            for model, harness, relative in (('opus', 'claude', '.local/bin/claude'),
                                             ('spark', 'muse', '.local/bin/muse'),
                                             ('astra', 'codex', '.npm-global/bin/codex'),
                                             ('grok', 'grokbuild', '.grok/bin/grok'),
                                             ('mimo', 'opencode', '.opencode/bin/opencode')):
                binary = caller / relative
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text('#!/bin/bash\nexit 0\n')
                binary.chmod(0o755)
                adapter = adapters / (harness + '.sh')
                adapter.write_text('#!/bin/bash\necho "fixture login is valid"\n')
                adapter.chmod(0o755)
            result = subprocess.run(['/bin/bash', '-c', 'set -eu\n' + setup + helpers + '''
smoke_home
for model in opus spark astra grok mimo; do model_unavailable "$model"; done
'''], env={**os.environ, 'HOME': str(caller), 'WORK': str(root / 'work'),
           'REPO': str(REPO), 'PATH': str(binaries), 'GROK_BIN_DIR': '',
           'AGENTKIT_ADAPTER_DIR': str(adapters)}, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')

    def test_smoke_keeps_webhook_get_check_without_posting(self):
        setup = SMOKE[SMOKE.index('smoke_home()'):SMOKE.index('# A bounded way')]
        check = SMOKE[SMOKE.index('# --- 5: notify'):SMOKE.index('# --- 5b:')]
        methods = []
        status = [200]

        class Hook(BaseHTTPRequestHandler):
            def do_GET(self):
                methods.append(self.command)
                self.send_response(status[0])
                self.end_headers()
                self.wfile.write(b'{}')

            def do_POST(self):
                methods.append(self.command)
                self.send_error(500)

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp, \
                ThreadingHTTPServer(('127.0.0.1', 0), Hook) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                caller = Path(tmp) / 'caller'
                (caller / '.agentkit/secrets').mkdir(parents=True)
                (caller / '.agentkit/secrets/discord_webhook').write_text(
                    f'http://127.0.0.1:{server.server_port}/hook')
                for code in (200, 403):
                    status[0] = code
                    env = {**os.environ, 'HOME': str(caller), 'REPO': str(REPO),
                           'WORK': str(Path(tmp) / str(code)), 'AK_NOTIFY_SINK': 'dry-run',
                           'PATH': f'{REPO / "bin"}:{os.environ["PATH"]}'}
                    env.pop('AGENTKIT_DISCORD_WEBHOOK', None)
                    result = subprocess.run(['bash', '-c', setup + '''
smoke_home
. "$REPO/tests/acceptance.sh"
''' + check + '\nfinish'], env=env, text=True, capture_output=True, timeout=20)
                    self.assertEqual(result.returncode, 0 if code == 200 else 1,
                                     result.stdout + result.stderr)
                    self.assertIn('webhook configured', result.stdout)
                    self.assertNotIn('no webhook configured', result.stdout)
                self.assertEqual(methods, ['GET', 'GET'])
            finally:
                server.shutdown()
                thread.join()

    def test_claude_stream_leaves_no_credential_links_in_output(self):
        start = SMOKE.index('smoke_home()')
        stream = SMOKE[start:SMOKE.index('usage_fresh_check()', start)]
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller = root / 'caller'
            (caller / '.codex').mkdir(parents=True)
            (caller / '.codex/auth.json').write_text('fixture login')
            for code in (0, 23):
                output = root / f'output-{code}'
                result = subprocess.run(['bash', '-c', '''set -eu
python3() {
  if [ "$1" = "$REPO/tests/check_claude_stream.py" ]; then
    test -L "$HOME/.codex/auth.json"
    test ! -L "$HOME/.codex"
    printf '%s\\n' "$HOME" >"$STREAM/sandbox-path"
    return "$FIXTURE_RC"
  fi
  command python3 "$@"
}
''' + stream, 'smoke.sh', '--claude-stream', str(output)],
                                        env={**os.environ, 'HOME': str(caller), 'REPO': str(REPO),
                                             'TMPDIR': tmp, 'FIXTURE_RC': str(code)},
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertFalse(Path((output / 'sandbox-path').read_text().strip()).exists())
                self.assertFalse((output / 'home').exists())
                self.assertFalse(any(path.is_symlink() for path in output.rglob('*')))

    def test_remote_derives_from_gh_api_user(self):
        for name, script in (("smoke.sh", SMOKE), ("e2e-fresh.sh", FRESH)):
            with self.subTest(gate=name):
                self.assertIn("gh api user", script)
                login = re.search(r"(\w*LOGIN)=\$\(gh api user --jq \.login", script)
                self.assertIsNotNone(login, f"{name} never reads its login off gh api user")
                remote = "agentkit-smoke" if name == "smoke.sh" else "agentkit-e2e"
                self.assertIn('SMOKE_REPO="$%s/%s"' % (login.group(1), remote), script)

    def test_remote_name_is_stable(self):
        for name, script, remote in (("smoke.sh", SMOKE, "agentkit-smoke"),
                                     ("e2e-fresh.sh", FRESH, "agentkit-e2e")):
            with self.subTest(gate=name):
                lines = [line for line in script.splitlines()
                         if line.strip().startswith("SMOKE_REPO=") and "agentkit-" in line]
                self.assertEqual(len(lines), 1, f"{name} has no single fixed remote: {lines}")
                self.assertRegex(lines[0], r'SMOKE_REPO="\$\w+/' + remote + r'"$')

    def test_remote_created_only_when_missing(self):
        for name, script in (("smoke.sh", SMOKE), ("e2e-fresh.sh", FRESH)):
            with self.subTest(gate=name):
                self.assertEqual(script.count('gh repo create "$SMOKE_REPO"'), 1)
                self.assertRegex(script, r'gh repo view "\$SMOKE_REPO" >/dev/null 2>&1 \|\|\s*'
                                         r'gh repo create "\$SMOKE_REPO" --private')

    def test_remote_reset_to_seed_before_run(self):
        for name, script in (("smoke.sh", SMOKE), ("e2e-fresh.sh", FRESH)):
            with self.subTest(gate=name):
                start = script.index('_LOGIN=$(gh api user')
                setup = script[start:script.index('cat >"$WORK/task.md"', start)]
                git = r'git(?: -C "\$CLONE")? '
                self.assertRegex(setup, git + r'reset --hard "\$\(' + git
                                 + r'rev-list --max-parents=0 HEAD\)"')
                self.assertIn('branch -M main', setup)
                self.assertIn('push -q --force -u origin main', setup)
                self.assertLess(setup.index('reset --hard'), setup.index('push -q --force'))
                self.assertIn('refs/remotes/origin/ak/', setup)
                self.assertIn('push -q origin --delete "$branch"', setup)

        # A legacy target's first commit held only a README, not the failing test.
        with tempfile.TemporaryDirectory(prefix=".open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            env = {**os.environ, "WORK": tmp, "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_CONFIG_NOSYSTEM": "1"}

            def run(*args):
                result = subprocess.run(args, cwd=root, env=env, capture_output=True,
                                        text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout.strip()

            run("git", "init", "-q", "--bare", "-b", "main", "origin.git")
            run("git", "clone", "-q", "origin.git", "legacy")
            run("git", "-C", "legacy", "config", "user.email", "test@localhost")
            run("git", "-C", "legacy", "config", "user.name", "test")
            (root / "legacy/README.md").write_text("old seed\n")
            run("git", "-C", "legacy", "add", "README.md")
            run("git", "-C", "legacy", "commit", "-qm", "seed")
            run("git", "-C", "legacy", "push", "-q", "origin", "main", "HEAD:ak/leftover")
            start = SMOKE.index('SMOKE_LOGIN=$(gh api user')
            setup = SMOKE[start:SMOKE.index('cat >"$WORK/task.md"', start)]
            fake = '''set -uo pipefail
gh() {
  case "$*" in
    'api user --jq .login') echo caller ;;
    'repo view caller/agentkit-smoke') test -d "$WORK/origin.git" ;;
    "repo clone caller/agentkit-smoke "*) git clone -q "$WORK/origin.git" "$4" ;;
    *) echo "unexpected gh command: $*" >&2; return 97 ;;
  esac
}
'''
            run("bash", "-c", fake + setup + '\ntest "$SRC" = 0')
            seed = run("git", "-C", "origin.git", "rev-parse", "main")
            self.assertEqual(run("git", "-C", "origin.git", "ls-tree", "-r", "--name-only", "main"),
                             "README.md\ntests/test_hello.py")
            self.assertEqual(run("git", "-C", "origin.git", "for-each-ref", "refs/heads/ak/"), "")
            (root / "agentkit-smoke/hello.py").write_text('def hello(): return "hello"\n')
            run("git", "-C", "agentkit-smoke", "add", "hello.py")
            run("git", "-C", "agentkit-smoke", "commit", "-qm", "previous fix")
            run("git", "-C", "agentkit-smoke", "push", "-q", "origin", "main", "HEAD:ak/old/run")
            shutil.rmtree(root / "agentkit-smoke")
            run("bash", "-c", fake + setup + '\ntest "$SRC" = 0')
            self.assertEqual(run("git", "-C", "origin.git", "rev-parse", "main"), seed)
            self.assertFalse((root / "agentkit-smoke/hello.py").exists())
            self.assertEqual(run("git", "-C", "origin.git", "for-each-ref", "refs/heads/ak/"), "")

    def test_remote_kept_without_extra_scope(self):
        for name, script in (("smoke.sh", SMOKE), ("e2e-fresh.sh", FRESH)):
            with self.subTest(gate=name):
                self.assertNotIn("repo delete", script)
                self.assertNotIn("delete_repo", script)

    def test_gates_need_no_privilege(self):
        for name, script in (("smoke.sh", SMOKE), ("e2e-fresh.sh", FRESH)):
            with self.subTest(gate=name):
                for banned in ("sudo", "useradd", "SUDO_USER"):
                    self.assertNotIn(banned, script, f"{name} still mentions {banned}")

    def test_no_personal_account_name_remains(self):
        banned = owner()
        paths = list((REPO / "tests").iterdir()) + [REPO / "install.sh", REPO / "docs/guide.md"]
        for path in sorted(paths):
            if path.is_file():
                with self.subTest(path=path.name):
                    self.assertNotIn(banned, path.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
