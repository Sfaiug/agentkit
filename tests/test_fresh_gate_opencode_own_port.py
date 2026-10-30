"""The fresh-install gate's OpenCode answers beside this host's own, and leaves no service behind."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
FRESH = (REPO / "tests/e2e-fresh.sh").read_text()
OPENCODE = r'''#!/bin/sh
conf=$HOME/.config/opencode/service.json   # OpenCode 2.1 beside another: its default port is taken
case "$1 $2" in
  "service set") mkdir -p "${conf%/*}" && echo "{\"port\": $4}" >"$conf" ;;
  "service stop") echo "stopped $HOME" >>"${0%/*}/stops" ;;
  api*) grep -q port "$conf" || exit 1; [ "$2" = provider.list ] && echo '{"data": []}' || echo '[]' ;;
esac
'''


class FreshGateOpenCodeOwnPort(unittest.TestCase):
    def test_opencode_answers_beside_the_hosts_own_and_its_service_is_stopped(self):
        step_c = FRESH[FRESH.index('  LENT=" "'):FRESH.index('  # `claude` also writes')]
        cleanup = FRESH[FRESH.index('cleanup() {'):FRESH.index('trap cleanup EXIT')]
        with tempfile.TemporaryDirectory(prefix=".ak-test-fresh-opencode-", dir=REPO) as tmp:
            (Path(tmp) / 'agentkit').symlink_to(REPO)
            for name, program in (('opencode', OPENCODE), ('security', '#!/bin/sh\nexit 97\n')):
                (Path(tmp) / name).write_text(program)
                (Path(tmp) / name).chmod(0o755)
            out = subprocess.run(
                ['/bin/bash', '-c', '. "$REPO/tests/acceptance.sh"\nbad=""\n' + step_c + 'echo "bad=$bad"\n'
                 'cleanup_logs() { :; }; tmux() { :; }\n'
                 + cleanup + 'cleanup\n'],
                env={'PATH': f'{tmp}:{os.environ["PATH"]}',   # its OpenCode and macOS's Keychain, which the lends ask
                     'HOME': f'{tmp}/caller', 'WORK': tmp, 'REPO': str(REPO), 'INVHOME': f'{tmp}/caller', 'UH': tmp,
                     'HOSTBIN': ' opencode ', 'EPATH': f'{tmp}:/usr/bin:/bin'},
                text=True, capture_output=True, timeout=60).stdout
            self.assertIn("SKIP  c: opencode's login is not on this host", out)
            self.assertIn('\nbad=; no harness here is installed with its login; the gate needs one\n', out)
            self.assertEqual((Path(tmp) / 'stops').read_text(), f'stopped {tmp}\n')


if __name__ == "__main__":
    unittest.main()
