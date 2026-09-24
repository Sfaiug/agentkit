"""Run smoke's notification checks verbatim with local state, tmux and fake adapters."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
TMUX = os.environ.get("AGENTKIT_SMOKE_TMUX") or shutil.which("tmux")


@unittest.skipUnless(TMUX and shutil.which("jq"), "requires tmux and jq")
class NotificationSmoke(unittest.TestCase):
    def check_section(self, number):
        source = (REPO / "tests/smoke.sh").read_text()
        with tempfile.TemporaryDirectory(prefix=".notify-smoke-", dir=REPO) as directory:
            root = Path(directory)
            binaries, sockets = root / "bin", root / "sockets"
            binaries.mkdir()
            sockets.mkdir(mode=0o700)
            # The wrapper never follows $TMUX or reaches a default/jobs/owner server.
            # A relative explicit socket also works in this checkout's long pathname.
            wrapper = binaries / "tmux"
            wrapper.write_text('''#!/usr/bin/env bash
set -eu
[ "${1:-} ${2:-}" = '-L agentkit-test' ] || exit 97
shift 2
cd -- "$TMUX_TMPDIR"
exec "$NOTIFY_SMOKE_TMUX" -L agentkit-test -S agentkit-test "$@"
''')
            wrapper.chmod(0o755)
            for name in ("claude", "codex", "muse", "gh", "ssh"):
                executable = binaries / name
                executable.write_text('#!/bin/sh\necho "unexpected external tool: $0" >&2\nexit 97\n')
                executable.chmod(0o755)
            # Every ak subprocess reads the same fake boot; no real reboot or host state.
            (binaries / "sitecustomize.py").write_text(
                'from agentkit import watch\nwatch.boot_id = lambda: "fake-notify-smoke-boot"\n')
            # AK_MAX_RUNS=0 as tests/smoke.sh exports it above every check: without it the
            # section's `ak run` waits for a slot on a busy host and outlives the timeout.
            env = {**os.environ, "HOME": str(root), "WORK": str(root), "REPO": str(REPO),
                   "AK_MAX_RUNS": "0",
                   "TMUX_TMPDIR": str(sockets), "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                   "NOTIFY_SMOKE_TMUX": TMUX, "TMPDIR": str(root), "NO_COLOR": "1",
                   "PATH": f"{binaries}:{REPO / 'bin'}:{os.environ['PATH']}",
                   "PYTHONPATH": f"{binaries}:{REPO}", "PYTHONDONTWRITEBYTECODE": "1",
                   "AGENTKIT_DISCORD_USER_ID": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
                   "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
                   "AK_RUN_LOG": "", "AGENTKIT_ADAPTER_DIR": str(root / "adapters")}
            env.pop("TMUX", None)
            (root / "adapters").mkdir()
            functions = []
            for start, end in (("newrepo() {", '\necho "workdir: $WORK"'),
                               ("fakeadapter() {", '\ncat >"$WORK/retry-task.md"')):
                functions.append(source[source.index(start):source.index(end, source.index(start))])
            if number == "g":
                certification = (REPO / "tests/e2e-fresh.sh").read_text()
                start = certification.index("# ==== g)")
                end = certification.index("# ==== d, closing:", start)
                checks = '''
UH="$WORK/home-e2e"
mkdir -p -- "$UH/.agentkit/secrets"
printf '424242\\n' >"$UH/.agentkit/secrets/discord_user_id"
tm new-session -d -s atoll sleep 60 || exit 1
tm set-option -t atoll @ak_orch 1 || exit 1
doing() { [ "$1" = g ]; }
as() { HOME="$UH" bash -c "$1"; }
must() { local message=$1; shift; "$@" >/dev/null 2>&1 || no "$message"; }
verdict() { [ "$NFAIL" = 0 ] && ok "$1"; }
''' + certification[start:end]
            else:
                start = source.index(f"# --- {number}:")
                end = source.index(f"# --- {number + 1}:", start)
                checks = source[start:end]
            script = root / "check.sh"
            script.write_text('set -uo pipefail\n. "$REPO/tests/acceptance.sh"\n'
                              'tm() { env -u TMUX tmux -L agentkit-test "$@"; }\n'
                              + "\n".join(functions)
                              + '\nfor harness in claude codex muse; do\n'
                              '  fakeadapter "$AGENTKIT_ADAPTER_DIR" "$harness" pass\ndone\n'
                              + checks + '\nfinish\n')
            proc = subprocess.Popen(["bash", str(script)], cwd=root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True)
            try:
                output = proc.communicate(timeout=60)[0]
                self.assertEqual(proc.returncode, 0, output)
                self.assertIn(f"PASS  {number} ", output)
                self.assertIn("1 passed, 0 failed, 0 skipped", output)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)
                subprocess.run([str(wrapper), "-L", "agentkit-test", "kill-server"],
                               cwd=root, env=env, capture_output=True, timeout=10)

    def test_check_21_shapes_preview_streams_and_menu(self):
        self.check_section(21)

    def test_check_29_orphan_delivery_and_sessionless_preview_streams(self):
        self.check_section(29)

    def test_e2e_step_g_notification_json_and_terminal_previews(self):
        self.check_section("g")


if __name__ == "__main__":
    unittest.main(verbosity=2)
