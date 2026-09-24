"""Bootstrap regressions. All writes stay in temporary directories inside this checkout."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'browser'))

import bootstrap
import runtime


class Bootstrap(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=REPO / 'browser')))
        self.root = self.home / '.local/share/browser-bridge'
        self.secrets = self.home / '.agentkit/secrets'
        self.account = SimpleNamespace(pw_name='new-agent', pw_dir=str(self.home))
        self.stack.enter_context(patch.dict(os.environ, {'HOME': str(self.home), 'TMPDIR': str(self.home)}))
        for module in (bootstrap, runtime):
            self.stack.enter_context(patch.object(module, 'ROOT', self.root))
            self.stack.enter_context(patch.object(module, 'SECRETS', self.secrets))
        for name in runtime.DEFAULT_PORTS:
            self.stack.enter_context(patch.dict(os.environ))
            os.environ.pop('BROWSER_BRIDGE_' + name.upper(), None)
        self.stack.enter_context(patch.object(bootstrap.pwd, 'getpwuid', return_value=self.account))
        self.stack.enter_context(patch.object(bootstrap.platform, 'system', return_value='Linux'))
        self.stack.enter_context(patch.object(bootstrap.socket, 'gethostname', return_value='new-host'))
        self.stack.enter_context(patch.object(sys, 'argv', ['bootstrap.py']))
        self.ports = {'cdp_port': 9333, 'vnc_port': 5999, 'novnc_port': 6099}

    def rendered(self, address='100.80.90.10'):
        return bootstrap.render(self.account, address, self.ports)

    def run_main(self, installed, address='100.80.90.10'):
        output = io.StringIO()
        with patch.object(bootstrap, 'installed_units', return_value=installed), \
                patch.object(bootstrap, 'tailscale_ipv4', return_value=address) as tailscale, \
                patch.object(bootstrap, 'settings', return_value=self.ports), \
                patch.object(bootstrap, 'ensure_packages') as packages, \
                patch.object(bootstrap, 'check_running') as running, \
                patch.object(bootstrap, 'install') as install, redirect_stdout(output), redirect_stderr(output):
            bootstrap.main()
        self.packages, self.running = packages, running
        return output.getvalue(), install, tailscale

    def test_foreign_account_skips_before_tailscale_or_writes(self):
        units = {name: text.replace('User=new-agent', 'User=another-owner')
                 for name, text in self.rendered().items()}
        output, install, tailscale = self.run_main(units)
        self.assertIn("User expected 'new-agent', found 'another-owner'", output)
        self.assertIn('browser step skipped', output)
        install.assert_not_called()
        tailscale.assert_not_called()
        self.packages.assert_not_called()
        self.running.assert_not_called()
        self.assertFalse(self.root.exists())
        self.assertFalse(self.secrets.exists())

    def test_foreign_host_skips_before_tailscale_or_writes(self):
        units = {name: text.replace('host: new-host', 'host: another-host')
                 for name, text in self.rendered().items()}
        output, install, tailscale = self.run_main(units)
        self.assertIn("Host expected 'new-host', found 'another-host'", output)
        install.assert_not_called()
        tailscale.assert_not_called()
        self.packages.assert_not_called()
        self.running.assert_not_called()

    def test_address_drift_names_key_and_expected_value(self):
        output, install, _ = self.run_main(self.rendered('100.80.90.20'))
        self.assertIn('browser-bridge-novnc.service: ExecStart expected', output)
        self.assertIn('100.80.90.10:6099', output)
        self.assertIn('100.80.90.20:6099', output)
        self.assertIn('browser step skipped', output)
        install.assert_not_called()
        self.packages.assert_not_called()
        self.running.assert_not_called()

    def test_matching_legacy_units_and_partial_stack_preserve_units(self):
        units = {name: '\n'.join(line for line in text.splitlines()
                                if not line.startswith(('# Browser bridge host:', 'Environment="HOME=')))
                 for name, text in self.rendered().items()}
        output, install, _ = self.run_main(units)
        self.assertIn('already installed', output)
        self.assertNotIn('expected', output)
        install.assert_not_called()
        self.packages.assert_called_once_with()
        self.running.assert_called_once_with()
        units.pop(bootstrap.UNITS[-1])
        output, install, _ = self.run_main(units)
        self.assertIn('expected an installed unit, found missing', output)
        install.assert_not_called()
        self.packages.assert_not_called()

    def test_missing_plaintext_preserves_rfbauth_and_points_to_login(self):
        self.secrets.mkdir(parents=True)
        auth = self.secrets / 'browser-bridge-vnc.rfbauth'
        auth.write_bytes(b'old-auth')
        output, install, _ = self.run_main(self.rendered())
        self.assertIn('ak browser login', output)
        self.assertIn('continuing browser checks', output)
        self.assertNotIn('browser step skipped', output)
        self.assertNotIn('restore them', output)
        self.assertEqual(auth.read_bytes(), b'old-auth')
        install.assert_not_called()
        self.packages.assert_called_once_with()
        self.running.assert_called_once_with()
        self.assertEqual(list(self.secrets.iterdir()), [auth])

    def test_fresh_rfbauth_only_install_creates_credentials_and_login_works(self):
        self.secrets.mkdir(parents=True)
        auth = self.secrets / 'browser-bridge-vnc.rfbauth'
        auth.write_bytes(b'old-auth')
        # Empty legacy plaintext is also missing, not a password to preserve.
        (self.secrets / 'browser-bridge-vnc').write_text('')
        output = io.StringIO()
        with patch.object(bootstrap, 'installed_units', return_value={}), \
                patch.object(bootstrap, 'tailscale_ipv4', return_value='100.80.90.10'), \
                patch.object(bootstrap, 'settings', return_value=self.ports), \
                patch.object(bootstrap, 'ensure_packages'), \
                patch.object(bootstrap.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='')), \
                redirect_stdout(output), redirect_stderr(output):
            bootstrap.main()
        self.assertIn('Browser bridge installed.', output.getvalue())
        self.assertNotIn('browser step skipped', output.getvalue())
        self.assertNotIn('ak browser login', output.getvalue())
        password = (self.secrets / 'browser-bridge-vnc').read_text().strip()
        self.assertEqual(len(password), 16)
        self.assertNotEqual(auth.read_bytes(), b'old-auth')
        self.assertNotIn(password, output.getvalue())

        sys.path.insert(0, str(REPO))
        from agentkit import browser
        with patch.object(browser, 'UNIT_DIR', self.root / 'rendered-units'), \
                patch.object(browser, 'SECRET', self.secrets / 'browser-bridge-vnc.txt'), \
                patch.object(browser, 'LEGACY', self.secrets / 'browser-bridge-vnc'), \
                patch.object(browser, 'RFBAUTH', auth), \
                patch.object(browser, 'mint', side_effect=AssertionError('login must reuse the new password')), \
                redirect_stdout(io.StringIO()) as login:
            self.assertEqual(browser.login([]), 0)
        self.assertIn('http://100.80.90.10:6099/vnc.html', login.getvalue())
        self.assertIn(password, login.getvalue())

    def test_render_uses_new_account_home_ports_and_loopback(self):
        # Rendering is read-only; these need not be real account directories on this host.
        for home in (Path('/srv/agents/another home'), Path('/srv/agents/percent% dollar$ quote"')):
            with patch.object(bootstrap, 'ROOT', home / 'bridge'), \
                    patch.object(bootstrap, 'SECRETS', home / 'secrets'):
                account = SimpleNamespace(pw_name='other-agent', pw_dir=str(home))
                units = bootstrap.render(account, '100.100.10.20', self.ports)
            joined = '\n'.join(units.values())
            self.assertNotRegex(joined, r'@[A-Z0-9_]+@|/home/|100\.(?!100\.10\.20\b)\d+\.\d+\.\d+')
            self.assertIn('User=other-agent', joined)
            chromium = bootstrap.service_values(units[bootstrap.UNITS[2]])['ExecStart']
            vnc = bootstrap.service_values(units[bootstrap.UNITS[3]])['ExecStart']
            novnc = bootstrap.service_values(units[bootstrap.UNITS[4]])['ExecStart']
            self.assertIn('--remote-debugging-address=127.0.0.1', chromium)
            self.assertIn('--remote-debugging-port=9333', chromium)
            self.assertIn('-localhost', vnc)
            self.assertEqual(vnc[vnc.index('-listen') + 1], '127.0.0.1')
            self.assertEqual(vnc[vnc.index('-rfbport') + 1], '5999')
            self.assertEqual(novnc[-2:], ('100.100.10.20:6099', '127.0.0.1:5999'))

    def test_tailscale_rejects_missing_public_ipv6_and_multiple_addresses(self):
        for value in ('', '0.0.0.0', '127.0.0.1', '192.168.0.1', '100.63.1.1',
                      '100.128.0.1', '100.80.0.999', 'fd7a::123', '100.80.0.1\n100.80.0.2'):
            with self.subTest(value=value), patch.object(bootstrap, 'capture', return_value=SimpleNamespace(
                    stdout=value, returncode=0)), self.assertRaises(ValueError):
                bootstrap.tailscale_ipv4()
        with patch.object(bootstrap, 'capture', return_value=SimpleNamespace(stdout='100.127.255.254\n', returncode=0)):
            self.assertEqual(bootstrap.tailscale_ipv4(), '100.127.255.254')

    def test_runtime_ports_are_persisted_validated_and_shared_with_helpers(self):
        self.root.mkdir(parents=True)
        (self.root / 'runtime.json').write_text(json.dumps(self.ports))
        self.assertEqual(runtime.endpoint(), 'http://127.0.0.1:9333')
        with patch.dict(os.environ, {'BROWSER_BRIDGE_CDP_PORT': '9444'}):
            self.assertEqual(runtime.endpoint(), 'http://127.0.0.1:9444')
        for value in ('0', '-1', '65536', '80', 'nope', '１２３４', '5999'):
            with patch.dict(os.environ, {'BROWSER_BRIDGE_CDP_PORT': value}), self.assertRaises(ValueError):
                runtime.settings()
        (self.root / 'runtime.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'expected a JSON object'):
            runtime.settings()

    def test_systemctl_dropin_owner_overrides_base(self):
        unit = self.rendered()[bootstrap.UNITS[0]]
        unit += '\n# /etc/systemd/system/browser-bridge-xvfb.service.d/owner.conf\n[Service]\nUser=foreign\n'
        output, install, _ = self.run_main({bootstrap.UNITS[0]: unit})
        self.assertIn("found 'foreign'", output)
        install.assert_not_called()

    def test_fresh_install_copies_complete_payload_and_preserves_password(self):
        self.secrets.mkdir(parents=True)
        plain = self.secrets / 'browser-bridge-vnc.txt'
        plain.write_text('TestPassword1234\n')
        # Stand in only for privileged/package/venv operations. File copies and credentials
        # are real, in this test's home, and no command can install a host unit.
        with patch.object(bootstrap, 'ensure_packages'), \
                patch.object(bootstrap.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='')) as run:
            bootstrap.install(self.rendered(), self.ports)
        self.assertEqual(plain.read_text(), 'TestPassword1234\n')
        self.assertEqual(plain.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.secrets / 'browser-bridge-vnc.rfbauth').stat().st_mode & 0o777, 0o600)
        for name in ('bootstrap.py', 'runtime.py', 'README.md', 'bridge.py', 'install.sh'):
            self.assertTrue((self.root / name).is_file(), name)
        self.assertIn('@USER@', (self.root / 'systemd' / bootstrap.UNITS[0]).read_text())
        self.assertIn('User=new-agent', (self.root / 'rendered-units' / bootstrap.UNITS[0]).read_text())
        self.assertEqual(runtime.settings(), self.ports)
        self.assertTrue(any(call.args[0][:4] == ('sudo', '-n', 'systemctl', 'restart')
                            for call in run.call_args_list))

    def test_fresh_install_without_passwordless_sudo_fails_before_any_writes(self):
        # All packages are present, so an apt invocation cannot serve as the sudo check.
        with patch.object(bootstrap, 'missing_packages', return_value=[]), \
                patch.object(bootstrap.subprocess, 'run', side_effect=subprocess.CalledProcessError(
                    1, ('sudo', '-n', 'true'))) as run, \
                patch.object(bootstrap, 'credentials') as credentials, \
                patch.object(bootstrap.urllib.request, 'urlopen') as download:
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.install(self.rendered(), self.ports)
        run.assert_called_once_with(('sudo', '-n', 'true'), check=True)
        credentials.assert_not_called()
        download.assert_not_called()
        self.assertFalse(self.root.exists())
        self.assertFalse(self.secrets.exists())

    def test_existing_stack_without_tailscale_is_nonfatal(self):
        self.secrets.mkdir(parents=True)
        (self.secrets / 'browser-bridge-vnc.rfbauth').write_bytes(b'old-auth')
        with patch.object(bootstrap, 'installed_units', return_value=self.rendered()), \
                patch.object(bootstrap, 'tailscale_ipv4', side_effect=FileNotFoundError('tailscale')), \
                patch.object(bootstrap, 'ensure_packages') as packages, \
                patch.object(bootstrap, 'check_running') as running, \
                patch.object(bootstrap, 'install') as install, redirect_stderr(io.StringIO()) as out:
            bootstrap.main()
        self.assertIn('browser step skipped', out.getvalue())
        self.assertIn('ak browser login', out.getvalue())
        install.assert_not_called()
        packages.assert_not_called()
        running.assert_not_called()

    def test_owner_repairs_missing_package_then_reports_stopped_unit(self):
        self.secrets.mkdir(parents=True)
        auth = self.secrets / 'browser-bridge-vnc.rfbauth'
        auth.write_bytes(b'old-auth')
        packages = set(bootstrap.PACKAGES) - {'imagemagick'}
        commands = []

        def capture(command):
            if command[0] == 'dpkg-query':
                present = command[-1] in packages
                return SimpleNamespace(returncode=0 if present else 1,
                                       stdout='install ok installed' if present else '', stderr='')
            self.assertEqual(command[:2], ['systemctl', 'is-active'])
            active = command[-1] != bootstrap.UNITS[3]
            return SimpleNamespace(returncode=0 if active else 3,
                                   stdout='active\n' if active else 'inactive\n', stderr='')

        def run(command, **kwargs):
            commands.append(command)
            if 'install' in command:
                self.assertEqual(command[-1], 'imagemagick')
                packages.add('imagemagick')
            return SimpleNamespace(returncode=0)

        with patch.object(bootstrap, 'installed_units', return_value=self.rendered()), \
                patch.object(bootstrap, 'tailscale_ipv4', return_value='100.80.90.10'), \
                patch.object(bootstrap, 'settings', return_value=self.ports), \
                patch.object(bootstrap, 'capture', side_effect=capture), \
                patch.object(bootstrap.subprocess, 'run', side_effect=run), \
                patch.object(bootstrap, 'install') as install, redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()) as output:
            with self.assertRaisesRegex(ValueError, "browser-bridge-x11vnc.service: ActiveState expected 'active', found 'inactive'"):
                bootstrap.main()
        self.assertEqual(commands, [
            ['sudo', '-n', 'apt-get', 'update'],
            ['sudo', '-n', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install',
             '-y', '--no-install-recommends', 'imagemagick'],
        ])
        install.assert_not_called()
        self.assertIn('ak browser login', output.getvalue())
        self.assertNotIn('browser step skipped', output.getvalue())
        self.assertEqual(auth.read_bytes(), b'old-auth')
        self.assertFalse(self.root.exists())

    def test_healthy_owner_rerun_needs_no_sudo(self):
        checked = []

        def capture(command):
            if command[0] == 'dpkg-query':
                return SimpleNamespace(returncode=0, stdout='install ok installed', stderr='')
            self.assertEqual(command[:2], ['systemctl', 'is-active'])
            checked.append(command[-1])
            return SimpleNamespace(returncode=0, stdout='active\n', stderr='')

        with patch.object(bootstrap, 'installed_units', return_value=self.rendered()), \
                patch.object(bootstrap, 'tailscale_ipv4', return_value='100.80.90.10'), \
                patch.object(bootstrap, 'settings', return_value=self.ports), \
                patch.object(bootstrap, 'capture', side_effect=capture), \
                patch.object(bootstrap.subprocess, 'run', side_effect=AssertionError('unexpected mutation')), \
                redirect_stdout(io.StringIO()) as output:
            bootstrap.main()
        self.assertEqual(checked, list(bootstrap.UNITS))
        self.assertIn('all 5 active', output.getvalue())
        self.assertFalse(self.root.exists())

    def test_package_repair_verifies_apt_result(self):
        with patch.object(bootstrap, 'missing_packages', return_value=['imagemagick']), \
                patch.object(bootstrap.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
                redirect_stdout(io.StringIO()), \
                self.assertRaisesRegex(ValueError, 'still missing: imagemagick'):
            bootstrap.ensure_packages()

    def test_main_installer_continues_every_section_after_foreign_stack(self):
        self.assert_installer_continues('foreign')

    def test_main_installer_continues_every_section_after_foreign_host(self):
        self.assert_installer_continues('foreign-host')

    def test_main_installer_continues_after_owner_health_check_fails(self):
        self.assert_installer_continues('stopped')

    def assert_installer_continues(self, stack):
        # Execute the production installer from section 3b through its final summary. Its
        # earlier package/harness setup is irrelevant here; all OS-facing commands below
        # are recorders, while browser preflight and both MCP registrations execute for real.
        fakebin = self.home / 'bin'
        fakebin.mkdir()
        def script(name, body):
            path = fakebin / name
            path.write_text('#!/bin/bash\nset -eu\n' + body)
            path.chmod(0o700)
        real_python = shlex.quote(sys.executable)
        script('python3', f'''if [[ "${{1:-}}" == */browser/bootstrap.py ]]; then
  exec {real_python} "$HOME/bootstrap-driver.py"
fi
exec {real_python} "$@"
''')
        (self.home / 'bootstrap-driver.py').write_text(f'''
import os, sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, {str(REPO / 'browser')!r})
import bootstrap
account = SimpleNamespace(pw_name='new-agent', pw_dir=os.environ['HOME'])
units = (bootstrap.render(account, '100.80.90.10', bootstrap.settings()) if {stack!r} != 'foreign'
         else {{bootstrap.UNITS[0]: '[Service]\\nUser=foreign-owner\\n'}})
if {stack!r} == 'foreign-host':
    units = {{name: text.replace('host: ' + bootstrap.socket.gethostname(), 'host: another-host')
             for name, text in units.items()}}
with patch.object(bootstrap.pwd, 'getpwuid', return_value=account), \\
     patch.object(bootstrap, 'installed_units', return_value=units), \\
     patch.object(bootstrap, 'tailscale_ipv4', return_value='100.80.90.10'), \\
     patch.object(bootstrap, 'ensure_packages'), \\
     patch.object(bootstrap, 'capture', return_value=SimpleNamespace(returncode=3, stdout='inactive', stderr='')):
    bootstrap.main()
''')
        script('ak', f'''exec {real_python} "$HOME/register-driver.py" "$@"
''')
        (self.home / 'register-driver.py').write_text(f'''
import sys
from unittest.mock import patch
sys.path.insert(0, {str(REPO)!r})
from agentkit import browser
assert sys.argv[1:] == ['browser', 'mcp-register'], sys.argv
with patch.object(browser, 'warm_npx', return_value='test: no network'):
    sys.exit(browser.mcp_register([]))
''')
        script('crontab', '''if [[ "$1" == -l ]]; then cat "$HOME/cron" 2>/dev/null; else cat >"$HOME/cron"; fi
''')
        script('tmux', '''echo "$*" >>"$HOME/tmux-calls"
if [[ "$*" == *" -F "* ]]; then exit 0; fi
''')
        for name in ('gh', 'tailscale', 'security'):
            script(name, 'exit 1\n')
        for name in ('claude', 'codex', 'muse'):
            script(name, 'exit 0\n')
        source = (REPO / 'install.sh').read_text()
        tail = source[source.index('# --- (3b)'):]
        prelude = f'''set -euo pipefail
REPO={shlex.quote(str(REPO))}
AK="$HOME/.agentkit"
BIN="$HOME/.local/bin"
NPM_PREFIX="$HOME/.npm-global"
ROLE=server SANDBOX=0 OS=Linux TTY=0
PHONE_KEY='ssh-ed25519 AAAAtest phone'
mkdir -p "$AK/state" "$AK/secrets" "$AK/tmp" "$BIN"
have() {{ command -v "$1" >/dev/null 2>&1; }}
note() {{ echo "note: $*" >&2; }}
py_ok() {{ python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; }}
'''
        environment = {**os.environ, 'PATH': f'{fakebin}:/usr/bin:/bin', 'AGENTKIT_TMUX_SOCKET': 'agentkit-test'}
        result = subprocess.run(['bash'], input=prelude + tail, env=environment, cwd=self.home,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if stack == 'foreign':
            self.assertIn("User expected 'new-agent', found 'foreign-owner'", result.stderr)
        elif stack == 'foreign-host':
            self.assertIn('the shared browser belongs to another host', result.stderr)
            self.assertIn('browser step skipped', result.stderr)
        else:
            self.assertIn('browser units not running', result.stderr)
            self.assertIn('browser step did not finish; continuing install', result.stderr)
        self.assertIn('summary:', result.stdout)
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())
        self.assertFalse((self.home / '.claude/CLAUDE.md').exists())
        self.assertIn('browser', json.loads((self.home / '.claude.json').read_text())['mcpServers'])
        self.assertIn('bypassPermissions', (self.home / '.claude/settings.json').read_text())
        self.assertIn('danger-full-access', (self.home / '.codex/config.toml').read_text())
        self.assertIn('# agentkit watch', (self.home / 'cron').read_text())
        self.assertIn('set -g mouse on', (self.home / 'tmux-calls').read_text())
        self.assertIn('set -g history-limit 50000', (self.home / 'tmux-calls').read_text())
        self.assertIn('ak attach', (self.home / '.ssh/authorized_keys').read_text())
        self.assertTrue((self.home / '.agentkit/state/installed-at').exists())
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
