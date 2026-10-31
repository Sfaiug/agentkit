"""The acceptance gates need nothing private and no privilege.

Both gates reuse a private remote under the caller's own account, reset to its seed before
each run, and the fresh gate runs in a throwaway HOME instead of a throwaway Unix account.
No fixed owner remains anywhere.
"""

from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
CLAUDE = json.dumps({'claudeAiOauth': {'accessToken': 'fixture', 'expiresAt': 4102444800000}})
CODEX = json.dumps({'OPENAI_API_KEY': 'fixture-key'})
GROK = json.dumps({'fixture': {'key': 'fixture-key', 'expires_at': '2100-01-01T00:00:00Z'}})


def owner():
    """The personal account name, built without writing it."""
    return "".join(chr(c) for c in (83, 102, 97, 105, 117, 103))


class OpenGates(unittest.TestCase):
    def setUp(self):
        # A fixture HOME must never borrow this test runner's overridden real logins.
        overrides = patch.dict(os.environ, {name: '' for name in
                               ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'XDG_CONFIG_HOME',
                                'XDG_DATA_HOME', 'GROK_HOME', 'GH_CONFIG_DIR',
                                'OPENCODE_CONFIG_DIR', 'OPENCODE_CONFIG', 'AGENTKIT_ACCOUNT')})
        overrides.start()
        self.addCleanup(overrides.stop)
        # Every harness binary a gate asks about is a fake, ahead of any this host installed:
        # each real adapter's `lend` then asks no real harness, nor macOS's Keychain, which no
        # HOME hides.
        fakes = tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-bin-", dir=REPO)
        self.addCleanup(fakes.cleanup)
        for name in ('claude', 'codex', 'muse', 'grok', 'opencode', 'agy', 'security'):
            (Path(fakes.name) / name).write_text('#!/bin/sh\nexit 97\n')
            (Path(fakes.name) / name).chmod(0o755)
        path = patch.dict(os.environ, {'PATH': f'{fakes.name}:{os.environ["PATH"]}'})
        path.start()
        self.addCleanup(path.stop)

    def test_smoke_links_only_credentials_never_caller_directories(self):
        setup = SMOKE[SMOKE.index('smoke_share_probes()'):SMOKE.index('# A bounded way')]
        credentials = ('.config/gh/hosts.yml', '.agentkit/secrets/claude_oauth_token',
                       '.local/share/browser-bridge/Xauthority')
        copies = {'.claude.json': json.dumps({'oauthAccount': {'accountUuid': 'fixture'},
                                            'mcpServers': {'fixture': {'command': 'true'}}}),
                  '.gitconfig': '[user]\nname = fixture\n',
                  '.config/gh/config.yml': 'git_protocol: https\n'}
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
            # The host's record of harness swaps is shared live: the sandbox runs its installs.
            swaps = '.agentkit/state/harness-swaps.json'
            self.assertEqual(links.pop(swaps).resolve(), caller / swaps)
            # The host's probe cadence is shared live: each probe file links the host's own file,
            # one the host may have yet to write, in a state directory that is there for it.
            probes = {name for name in links if name.startswith('.agentkit/state/')}
            self.assertTrue(probes)
            for name in probes:
                self.assertRegex(name, r'-probe\.(lock|retry)$')
                self.assertEqual(links.pop(name).resolve(), caller / name)
                self.assertFalse((caller / name).is_dir(), f'{name} links a directory')
            self.assertEqual(set(links), set(credentials))
            for name, path in links.items():
                self.assertTrue(path.is_file(), f'{name} links a directory')
                self.assertEqual(path.resolve(), caller / name)
            for name, value in copies.items():
                self.assertEqual((home / name).read_text(), value)
                (home / name).write_text('sandbox edit')
                self.assertEqual((caller / name).read_text(), value)
            # A login the caller has that cannot be read, itself or through its link, ends the
            # suite, and so does one the sandbox cannot take: never an absence.
            (root / 'vault').mkdir()
            hosts = caller / '.config/gh/hosts.yml'
            hosts.rename(root / 'vault/hosts.yml')
            hosts.symlink_to(root / 'vault/hosts.yml')
            for broken, said in ((hosts, f'cannot read {hosts}'), (hosts.parent, f'cannot read {hosts}'),
                                 (root / 'vault', f'cannot read {hosts}'),
                                 (home / '.config', 'mkdir'), (home / '.claude.json', 'cp')):
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
            # A login whose missing directory sits directly under `/`, as GH_CONFIG_DIR=/gh, is
            # absent, just as one under a missing directory in /tmp is.
            missing = f'/.open-gates-{os.getpid()}'
            self.assertFalse(os.path.lexists(missing))
            shutil.rmtree(home)
            result = subprocess.run(['bash', '-c', setup + '\nsmoke_home'],
                                    env={**os.environ, 'HOME': str(caller), 'GH_CONFIG_DIR': missing,
                                         'REPO': str(REPO), 'WORK': str(root / 'work')},
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(os.path.lexists(home / '.config/gh/hosts.yml'))
            # A login the worker box withholds reads as /dev/null there: absent, not broken.
            hosts.unlink()
            hosts.symlink_to('/dev/null')
            shutil.rmtree(home)
            result = subprocess.run(['bash', '-c', setup + '\nsmoke_home'],
                                    env={**os.environ, 'HOME': str(caller), 'REPO': str(REPO),
                                         'WORK': str(root / 'work')},
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(os.path.lexists(home / '.config/gh/hosts.yml'))

    def test_smoke_borrows_overridden_logins_before_clearing_overrides(self):
        setup = SMOKE[SMOKE.index('smoke_share_probes()'):SMOKE.index('# A bounded way')]
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller, home = root / 'caller', root / 'work/home'
            caller.mkdir()
            overrides = {name: str(root / name.lower()) for name in
                         ('CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'XDG_CONFIG_HOME',
                          'XDG_DATA_HOME', 'GROK_HOME', 'GH_CONFIG_DIR', 'OPENCODE_CONFIG_DIR')}
            sources = {'.config/gh/hosts.yml': ('GH_CONFIG_DIR', 'hosts.yml'),
                       '.claude.json': ('CLAUDE_CONFIG_DIR', '.claude.json'),
                       '.config/gh/config.yml': ('GH_CONFIG_DIR', 'config.yml')}
            for name, (override, relative) in sources.items():
                path = Path(overrides[override]) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'source': name}))
            (Path(overrides['CLAUDE_CONFIG_DIR']) / '.credentials.json').write_text(CLAUDE)
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
                if name.endswith('hosts.yml'):
                    self.assertEqual((home / name).resolve(), Path(overrides[override]) / relative)
            lent = home / '.claude/.credentials.json'
            self.assertEqual((lent.read_text(), lent.is_symlink()), (CLAUDE, False))

    def test_smoke_mcp_claude_uses_worker_token_instead_of_refreshing_seat(self):
        block = SMOKE[SMOKE.index('  BP=\'Use the browser MCP'):
                      SMOKE.index('  if SMOKE_LOGIN=usual skip_spent 31e')]
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
        setup = SMOKE[SMOKE.index('smoke_share_probes()'):SMOKE.index('# A bounded way')]
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
            # A host that ran agentkit has its state directory, where the shared probe files live.
            (caller / '.agentkit/state').mkdir()
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
        setup = SMOKE[SMOKE.index('smoke_share_probes()'):SMOKE.index('# A bounded way')]
        flags = SMOKE[SMOKE.index('codex_model_flag_check()'):SMOKE.index('# Fake-adapter loops:')]
        shipped = (REPO / 'config.default.toml').read_text()
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
            for name in ('agentkit', 'adapters', 'tools', 'hooks', 'tests'):
                (fixture / name).symlink_to(REPO / name)
            (fixture / 'config.default.toml').write_text(shipped)
            # Only setup receives SMOKE_CALLER_HOME to borrow live model choices and probe
            # logins. Every Python in the extracted checks must read the sandbox's config.
            (fixture / 'sitecustomize.py').write_text('''import os, sys
def guard(event, args):
    if (event == 'open' and args[0] == os.environ['FORBIDDEN_CONFIG']
            and 'SMOKE_CALLER_HOME' not in os.environ):
        raise AssertionError('smoke read the caller config')
sys.addaudithook(guard)
''')
            config_path = caller / '.agentkit/config.toml'
            for index, content in enumerate((re.sub(r'(\[models\.astra\][^\[]*?model = )"[^"]*"', r'\1"pinned"', shipped)
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
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
        # None of the harnesses check 3 calls is here: each is named as not checked, never
        # counted as passed, and the suite fails, because it made no real call at all.
        start = SMOKE.index('model_unavailable()')
        helpers = SMOKE[start:SMOKE.index('U="$WORK/usage.json"', start)]
        check = SMOKE[SMOKE.index('# --- 3:'):SMOKE.index('# --- 3a:')]
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
        for line in ('3 claude: claude', '3 codex: codex', '3 muse: muse',
                     '3 grokbuild: grok', '3 antigravity: agy', '3 opencode: opencode'):
            self.assertIn(f'NOT CHECKED  {line} is not installed', result.stdout)
        self.assertIn('FAIL  3: no harness here is installed with its login', result.stdout)
        self.assertIn('0 passed, 1 failed, 0 skipped', result.stdout)

    def test_gates_pass_or_fail_on_their_own_under_an_outer_suites_diversion(self):
        # Run inside a running suite, each check inherits that suite's diversion log; its own
        # `finish` reads only what this check diverted.
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-outer-", dir=REPO) as outer:
            log = Path(outer) / 'notify-diversions.log'
            log.write_text("an outer suite's diversion\n")
            with patch.dict(os.environ, {'AK_NOTIFY_SINK_LOG': str(log)}):
                self.test_smoke_needs_one_harness_with_its_login()
                self.test_smoke_keeps_webhook_get_check_without_posting()

    def test_fresh_borrows_what_this_host_has_and_needs_one_harness(self):
        block = FRESH[FRESH.index("  # Each harness's login is a copy"):
                      FRESH.index('  # `claude` also writes')]

        def gate(hostbin, logins, answers, broken=()):
            """Step c's borrowing, with each adapter's `auth` answering "<exit> <line>"."""
            with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
                script = ('. "$REPO/tests/acceptance.sh"\nbad=""\n' + block
                          + 'printf "HERE=%s\\nSEAT=%s\\nbad=%s\\n" "$HERE" "$SEATLOGIN" "$bad"\n'
                          'finish')
                result = subprocess.run(['/bin/bash', '-c', script],
                                        env={**os.environ, 'WORK': tmp, 'REPO': str(REPO),
                                             'HOME': str(caller), 'INVHOME': str(caller), 'UH': str(home),
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
        # Claude's own login lent is the menu's seat, whatever the step makes of it.
        out, _, _, _ = gate('claude', {'.agentkit/secrets/claude_oauth_token': 'fixture token',
                                       '.claude/.credentials.json': CLAUDE},
                            {'claude': '0 fixture: worker token'})
        self.assertIn('HERE= claude:anthropic\nSEAT=1\nbad=\n', out)
        # A Grok-only host lends a copy of its login, and links nothing.
        out, links, copies, _ = gate('grok', {'.grok/auth.json': GROK},
                                     {'grokbuild': '0 grok: logged in'})
        self.assertIn('HERE= grokbuild:-\nSEAT=\nbad=\n', out)
        self.assertEqual((links, list(copies)), ({}, ['.grok/auth.json']))
        # OpenCode's settings with no key in them lend no login: its refusal is a skip, and the
        # Discord secret is a copy.
        out, links, copies, _ = gate('claude opencode',
                                     {'.agentkit/secrets/claude_oauth_token': 'fixture token',
                                      '.config/opencode/opencode.json': '{"theme": "dark"}',
                                      '.agentkit/secrets/discord_webhook': 'fixture webhook'},
                                     {'claude': '0 fixture: worker token',
                                      'opencode': '1 opencode: no provider key; run opencode auth login'})
        self.assertIn('HERE= claude:anthropic\nSEAT=\nbad=\n', out)
        self.assertIn("SKIP  c: opencode's login is not on this host: opencode: no provider key", out)
        self.assertEqual(set(links), {'.agentkit/secrets/claude_oauth_token'})
        self.assertEqual(copies, {'.agentkit/secrets/discord_webhook': 'fixture webhook'})
        # Its silence with none lent is a skip too: a new HOME's first OpenCode is slow to start.
        out, _, _, _ = gate('claude opencode', {'.agentkit/secrets/claude_oauth_token': 'fixture token'},
                            {'claude': '0 fixture: worker token',
                             'opencode': '2 opencode: provider discovery unavailable for mimo'})
        self.assertIn('HERE= claude:anthropic\nSEAT=\nbad=\n', out)
        self.assertIn("SKIP  c: opencode's login is not on this host, and its auth gave no answer: "
                      "opencode: provider discovery unavailable for mimo", out)
        # A lent login refused or unanswered in time, a lend that fails, or a worker token unreadable
        # or that cannot be linked fails, for every harness; no harness at all fails.
        codex, token = {'.codex/auth.json': CODEX}, '.agentkit/secrets/claude_oauth_token'
        worker = ('claude', {token: 'fixture'}, {'claude': '0 fixture: worker token'})
        for host, logins, answers, broken, why in (
                ('codex', codex, {'codex': '1 codex: the token expired'},
                 (), 'bad=; codex: the token expired'),
                ('grok', {'.grok/auth.json': GROK}, {'grokbuild': '1 grok: the login is expired'},
                 (), 'bad=; grok: the login is expired'),
                ('codex', codex, {'codex': '2 codex: jq is missing'},
                 (), 'bad=; codex: its auth gave no answer: codex: jq is missing'),
                ('codex', codex, {'codex': 'hang'},
                 (), 'bad=; codex: its auth gave no answer: ; no harness here'),
                ('codex', codex, {'codex': '0'},
                 (), 'bad=; codex: its auth gave no answer: ; no harness here'),
                ('codex', codex, {'codex': '0 codex: fine'},
                 (('home', '.codex'),), "bad=; this host's logins could not be lent"),
                (*worker, (('caller', token),), 'claude_oauth_token cannot be read'),
                (*worker, (('caller', '.agentkit/secrets'),), 'claude_oauth_token cannot be read'),
                (*worker, (('link', token),), 'claude_oauth_token cannot be read'),
                (*worker, (('home', '.agentkit'),), 'claude_oauth_token could not be linked into the new HOME'),
                ('', {}, {}, (), 'bad=; no harness here is installed with its login; the gate needs one')):
            with self.subTest(why=why, broken=broken):
                out, _, _, _ = gate(host, logins, answers, broken)
                self.assertIn(why, out)

    def test_smoke_finds_installer_binaries_without_login_shell_path(self):
        setup = SMOKE[SMOKE.index('smoke_share_probes()'):SMOKE.index('# A bounded way')]
        start = SMOKE.index('model_unavailable()')
        helpers = SMOKE[start:SMOKE.index('U="$WORK/usage.json"', start)]
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
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
                adapter.write_text('#!/bin/bash\n[ "$1" != lend ] || exit 1\necho "fixture login is valid"\n')
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
        setup = SMOKE[SMOKE.index('smoke_share_probes()'):SMOKE.index('# A bounded way')]
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

        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp, \
                ThreadingHTTPServer(('127.0.0.1', 0), Hook) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                caller = Path(tmp) / 'caller'
                (caller / '.agentkit/secrets').mkdir(parents=True)
                hook = f'http://127.0.0.1:{server.server_port}/hook'
                (caller / '.agentkit/secrets/discord_webhook').write_text(hook)
                # the file's webhook, then the one the caller's environment names instead
                for code, inherited in ((200, ''), (403, ''), (200, hook)):
                    status[0] = code
                    if inherited:
                        (caller / '.agentkit/secrets/discord_webhook').unlink()
                    env = {**os.environ, 'HOME': str(caller), 'REPO': str(REPO),
                           'WORK': str(Path(tmp) / f'{code}{inherited and "-env"}'),
                           'AK_NOTIFY_SINK': 'dry-run', 'AGENTKIT_DISCORD_WEBHOOK': inherited,
                           'PATH': f'{REPO / "bin"}:{os.environ["PATH"]}'}
                    result = subprocess.run(['bash', '-c', setup + '''
smoke_home
. "$REPO/tests/acceptance.sh"
''' + check + '\nfinish'], env=env, text=True, capture_output=True, timeout=20)
                    self.assertEqual(result.returncode, 0 if code == 200 else 1,
                                     result.stdout + result.stderr)
                    self.assertIn('webhook configured', result.stdout)
                    self.assertNotIn('no webhook configured', result.stdout)
                self.assertEqual(methods, ['GET', 'GET', 'GET'])
            finally:
                server.shutdown()
                thread.join()

    def test_smoke_fails_a_webhook_it_cannot_use(self):
        # Kept out of the suite's HOME, the webhook is still checked as it was there: a blank
        # file is configured and fails check 5, and one that cannot be read ends the setup,
        # whatever the environment names instead.
        setup = SMOKE[SMOKE.index('smoke_share_probes()'):SMOKE.index('# A bounded way')]
        check = SMOKE[SMOKE.index('# --- 5: notify'):SMOKE.index('# --- 5b:')]
        cases = [('\n', '', 1, 'webhook configured but not reachable'),
                 ('\0\n', '', 1, 'webhook configured but not reachable'),
                 (Path('/nonexistent/hook'), 'https://example.invalid/env', 1, 'cannot read')]
        if Path('/proc/self/mem').exists():
            cases.append((Path('/proc/self/mem'), '', 1, ''))
        for content, inherited, code, said in cases:
            with self.subTest(content=content, inherited=inherited), \
                    tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
                webhook = Path(tmp) / 'caller/.agentkit/secrets/discord_webhook'
                webhook.parent.mkdir(parents=True)
                if isinstance(content, Path):
                    webhook.symlink_to(content)
                else:
                    webhook.write_text(content)
                env = {**os.environ, 'HOME': str(Path(tmp) / 'caller'), 'REPO': str(REPO),
                       'WORK': str(Path(tmp) / 'work'), 'AK_NOTIFY_SINK': 'dry-run',
                       'AGENTKIT_DISCORD_WEBHOOK': inherited,
                       'PATH': f'{REPO / "bin"}:{os.environ["PATH"]}'}
                result = subprocess.run(['bash', '-c', setup + '''
smoke_home
. "$REPO/tests/acceptance.sh"
''' + check + '\nfinish'], env=env, text=True, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn(said, result.stdout + result.stderr)

    def test_claude_stream_leaves_no_credential_links_in_output(self):
        start = SMOKE.index('smoke_share_probes()')
        stream = SMOKE[start:SMOKE.index('usage_fresh_check()', start)]
        with tempfile.TemporaryDirectory(prefix=".ak-test-open-gates-", dir=REPO) as tmp:
            root = Path(tmp)
            caller = root / 'caller'
            (caller / '.config/gh').mkdir(parents=True)
            (caller / '.config/gh/hosts.yml').write_text('fixture login')
            for code in (0, 23):
                output = root / f'output-{code}'
                result = subprocess.run(['bash', '-c', '''set -eu
python3() {
  if [ "$1" = "$REPO/tests/check_claude_stream.py" ]; then
    test -L "$HOME/.config/gh/hosts.yml"
    test ! -L "$HOME/.config/gh"
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

    def test_remote_kept_without_extra_scope(self):
        for name, script in (("smoke.sh", SMOKE), ("e2e-fresh.sh", FRESH),
                             ("sandbox_branch.py", (REPO / "tests/sandbox_branch.py").read_text())):
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
        paths = list((REPO / "tests").iterdir()) + [REPO / "install.sh"]
        for path in sorted(paths):
            if path.is_file():
                with self.subTest(path=path.name):
                    self.assertNotIn(banned, path.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
