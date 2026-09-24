"""Install a fresh shared browser; preserve existing units and browser sessions."""
import ctypes
import ctypes.util
import ipaddress
import json
import os
from pathlib import Path
import platform
import pwd
import re
import secrets
import shlex
import shutil
import socket
import string
import struct
import subprocess
import sys
import urllib.request

from runtime import ROOT, SECRETS, settings

SOURCE = Path(__file__).resolve().parent
UNITS = tuple(f'browser-bridge-{part}.service'
              for part in ('xvfb', 'openbox', 'chromium', 'x11vnc', 'novnc'))
PACKAGES = ('chromium', 'xvfb', 'x11vnc', 'novnc', 'websockify', 'openbox',
            'fonts-dejavu', 'fonts-noto-core', 'fonts-noto-color-emoji', 'xdotool', 'imagemagick')


def capture(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


def installed_units():
    found = {}
    for unit in UNITS:
        # systemctl cat includes drop-ins and units from /run or the vendor directories,
        # so a foreign stack is not missed just because it is outside /etc.
        result = capture(['systemctl', 'cat', '--no-pager', unit])
        if result.returncode == 0:
            found[unit] = result.stdout
        else:
            path = Path('/etc/systemd/system') / unit
            if path.exists() or path.is_symlink():
                found[unit] = path.read_text()
            elif capture(['systemctl', 'show', '--property=LoadState', '--value', unit]).stdout.strip() != 'not-found':
                raise ValueError(f'cannot inspect {unit}; existing browser stack left untouched')
    return found


def service_values(text):
    """Compare directive values, allowing systemctl headers, quoting and drop-in resets."""
    result, section = {}, ''
    text = re.sub(r'\\\n\s*', ' ', text)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('['):
            section = line
        if section != '[Service]' or '=' not in line or line.startswith(('#', ';')):
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if key == 'Environment':
            if not value:
                result = {k: v for k, v in result.items() if not k.startswith('Environment.')}
            for assignment in shlex.split(value):
                name, _, val = assignment.partition('=')
                result['Environment.' + name] = (val,)
        elif value:
            result[key] = tuple(shlex.split(value))
        else:
            result.pop(key, None)
    return result


def tailscale_ipv4():
    result = capture(['tailscale', 'ip', '-4'])
    value = result.stdout.strip()
    if result.returncode != 0:
        raise ValueError('Tailscale IPv4 is unavailable; run `sudo tailscale up` on this host')
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise ValueError(f'Tailscale IPv4: expected one IPv4 address, got {value!r}') from None
    if address not in ipaddress.IPv4Network('100.64.0.0/10'):
        raise ValueError(f'Tailscale IPv4: expected an address in 100.64.0.0/10, got {value!r}')
    return str(address)


def render(account, address, ports):
    values = dict(USER=account.pw_name, HOME=account.pw_dir, TARGET=str(ROOT),
                  SECRETS=str(SECRETS), TAILSCALE_IPV4=address,
                  HOST=socket.gethostname(), **{k.upper(): str(v) for k, v in ports.items()})
    for key, value in values.items():
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError(f'{key}: control characters cannot be used in a systemd unit')
    rendered = {}
    for unit in UNITS:
        lines = []
        for line in (SOURCE / 'systemd' / unit).read_text().splitlines(keepends=True):
            def replace(match):
                value = values[match[1]].replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
                return value.replace('$', '$$') if line.startswith('Exec') else value
            lines.append(re.sub(r'@([A-Z0-9_]+)@', replace, line))
        rendered[unit] = ''.join(lines)
    return rendered


def missing_plaintext():
    return (SECRETS / 'browser-bridge-vnc.rfbauth').exists() and not any(
        path.exists() and path.read_text().strip()
        for path in (SECRETS / 'browser-bridge-vnc.txt', SECRETS / 'browser-bridge-vnc'))


def warn(message):
    print(f'warning: browser step skipped: {message}; continuing the rest of install.sh', file=sys.stderr)


def preflight(account, installed, rendered):
    """Report value differences and return whether all installed units match."""
    differences = []
    for unit, actual in installed.items():
        current, wanted = service_values(actual), service_values(rendered[unit])
        for key, value in wanted.items():
            if current.get(key) != value:
                # HOME was implicit in older system units; a missing explicit HOME is harmless.
                if key == 'Environment.HOME' and key not in current:
                    continue
                differences.append(f'{unit}: {key} expected {shlex.join(value)!r}, '
                                   f'found {shlex.join(current.get(key, ()))!r}')
    if installed:
        differences.extend(f'{unit}: expected an installed unit, found missing'
                           for unit in UNITS if unit not in installed)
        if differences:
            warn('existing units differ from this account/host; ' + '; '.join(differences)
                 + '. Existing units and browser sessions were left untouched')
        else:
            print(f'Browser bridge already installed for {account.pw_name}; units and sessions left untouched.')
    return not differences


def missing_packages():
    missing = []
    for package in PACKAGES:
        result = capture(['dpkg-query', '-W', '-f=${Status}', package])
        if result.returncode != 0 or result.stdout.strip() != 'install ok installed':
            missing.append(package)
    return missing


def ensure_packages():
    missing = missing_packages()
    if missing:
        print(f'Browser packages: installing {", ".join(missing)}')
        for command in (
            ['sudo', '-n', 'apt-get', 'update'],
            ['sudo', '-n', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install',
             '-y', '--no-install-recommends', *missing],
        ):
            subprocess.run(command, check=True, timeout=15 * 60)
        still = missing_packages()
        if still:
            raise ValueError(f'apt-get reported success but browser packages are still missing: {", ".join(still)}')
    print(f'Browser packages: all {len(PACKAGES)} present')


def check_running():
    down = []
    for unit in UNITS:
        result = capture(['systemctl', 'is-active', unit])
        if result.returncode != 0 or result.stdout.strip() != 'active':
            state = result.stdout.strip() or result.stderr.strip() or 'unknown'
            down.append(f'{unit}: ActiveState expected \'active\', found {state!r}')
    if down:
        raise ValueError('browser units not running: ' + '; '.join(down) + '; run `ak browser status` for details')
    print(f'Browser units: all {len(UNITS)} active; browser sessions left untouched.')


def credentials():
    # No password in command arguments, environment, stdout or stderr. Preserve the name
    # `ak browser login` uses today as well as the legacy plaintext filename.
    plain = next((path for path in (SECRETS / 'browser-bridge-vnc.txt', SECRETS / 'browser-bridge-vnc')
                  if path.exists() and path.read_text().strip()), SECRETS / 'browser-bridge-vnc')
    auth = SECRETS / 'browser-bridge-vnc.rfbauth'
    if not plain.exists() or not plain.read_text().strip():
        with plain.open('w' if plain.exists() else 'x') as out:
            out.write(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16)) + '\n')
    plain.chmod(0o600)
    password = plain.read_text().strip()
    if len(password) != 16 or not password.isascii() or not password.isalnum():
        raise ValueError('Existing VNC password must contain 16 ASCII alphanumeric characters; preserved unchanged')
    library = ctypes.util.find_library('vncserver')
    if library is None:
        raise ValueError('libvncserver is missing; install x11vnc first')
    store = ctypes.CDLL(library).rfbEncryptAndStorePasswd
    store.argtypes, store.restype = [ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int
    temporary = auth.with_name(auth.name + '.tmp')
    try:
        if store(password.encode(), os.fsencode(temporary)) != 0:
            raise ValueError('Failed to generate VNC authentication file')
        temporary.chmod(0o600)
        temporary.replace(auth)
    finally:
        temporary.unlink(missing_ok=True)
    xauth = ROOT / 'Xauthority'
    if not xauth.exists():
        def field(value):
            return struct.pack('!H', len(value)) + value
        with xauth.open('xb') as out:
            out.write(struct.pack('!H', 65535) + field(b'') + field(b'99')
                      + field(b'MIT-MAGIC-COOKIE-1') + field(secrets.token_bytes(16)))
    xauth.chmod(0o600)


def install(rendered, ports):
    def run(*args):
        subprocess.run(args, check=True)
    # Check even when every package is present, before creating files or downloading pip.
    run('sudo', '-n', 'true')
    ensure_packages()
    for path in (ROOT, ROOT / 'profile', ROOT / 'systemd', ROOT / 'rendered-units', SECRETS):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)
    if SOURCE != ROOT:
        for name in ('install.sh', 'bootstrap.py', 'runtime.py', 'bridge.py', 'wait-ready.py',
                     'stop-chromium.py', 'prepare-profile.py', 'requirements.txt', 'README.md'):
            shutil.copyfile(SOURCE / name, ROOT / name)
            (ROOT / name).chmod(0o700 if name in ('install.sh', 'bridge.py') else 0o600)
        for unit in UNITS:
            shutil.copyfile(SOURCE / 'systemd' / unit, ROOT / 'systemd' / unit)
            (ROOT / 'systemd' / unit).chmod(0o600)
    (ROOT / 'runtime.json').write_text(json.dumps(ports) + '\n')
    (ROOT / 'runtime.json').chmod(0o600)
    credentials()
    python = ROOT / 'venv/bin/python'
    if not python.exists():
        run(sys.executable, '-m', 'venv', '--without-pip', str(ROOT / 'venv'))
    if capture([str(python), '-m', 'pip', '--version']).returncode != 0:
        pip = ROOT / 'pip.pyz'
        try:
            with urllib.request.urlopen('https://bootstrap.pypa.io/pip/pip.pyz', timeout=60) as source:
                pip.write_bytes(source.read())
            run(str(python), str(pip), 'install', '--disable-pip-version-check', 'pip')
        finally:
            pip.unlink(missing_ok=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                    '-r', str(ROOT / 'requirements.txt')], check=True,
                   env={**os.environ, 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1'})
    for unit, text in rendered.items():
        path = ROOT / 'rendered-units' / unit
        path.write_text(text)
        path.chmod(0o600)
        run('sudo', '-n', 'install', '-m', '644', str(path), f'/etc/systemd/system/{unit}')
    run('sudo', '-n', 'systemctl', 'daemon-reload')
    run('sudo', '-n', 'systemctl', 'enable', *UNITS)
    run('sudo', '-n', 'systemctl', 'restart', *UNITS)


def main():
    if len(sys.argv) != 1:
        raise ValueError('browser/install.sh takes no arguments')
    if platform.system() != 'Linux' or shutil.which('systemctl') is None:
        warn('the shared stack requires Linux with systemd')
        return
    account = pwd.getpwuid(os.getuid())
    if Path.home().resolve() != Path(account.pw_dir).resolve():
        warn(f'HOME expected {account.pw_dir!r} for {account.pw_name}; sandbox HOME cannot install system units')
        return
    installed = installed_units()
    # Ownership is checked before Tailscale, secrets, packages, or any other writes.
    for unit, text in installed.items():
        user = service_values(text).get('User', ())
        if user != (account.pw_name,):
            warn(f'{unit}: User expected {account.pw_name!r}, found {shlex.join(user)!r}; '
                 'the shared browser belongs to another account and was left untouched')
            return
        host = re.search(r'^# Browser bridge host: (.+)$', text, re.M)
        if host and host[1] != socket.gethostname():
            warn(f'{unit}: Host expected {socket.gethostname()!r}, found {host[1]!r}; '
                 'the shared browser belongs to another host and was left untouched')
            return
    try:
        if installed and missing_plaintext():
            print(f'warning: {SECRETS / "browser-bridge-vnc.rfbauth"} exists but its plaintext password is missing; '
                  f'run `ak browser login` as {account.pw_name} to mint a new password; '
                  'existing authentication preserved, continuing browser checks', file=sys.stderr)
        ports = settings()
        address = tailscale_ipv4()
        rendered = render(account, address, ports)
        matching = preflight(account, installed, rendered)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if not installed:
            raise
        warn(f'{exc}; existing units and browser sessions left untouched')
        return
    if installed:
        # Only a matching owner stack gets package repair. Foreign units, host/value
        # mismatches and partial stacks must not trigger an install or restart.
        if matching:
            ensure_packages()
            check_running()
        return
    install(rendered, ports)
    print('Browser bridge installed. VNC password preserved in the private secrets directory.')
    print(f'http://{address}:{ports["novnc_port"]}/vnc.html?autoconnect=1&resize=remote')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'browser bootstrap: {exc}', file=sys.stderr)
        sys.exit(1)
