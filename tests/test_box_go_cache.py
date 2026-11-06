"""Every box writes the account's Go build cache, wherever `go env -w` saved it, so what one turn,
check or proof compiled serves the next (tests/test_key_a_turn_builds_go.py), and a check boxed
inside a turn still writes its HOME for nothing."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
from fixtures.sandbox import account_home  # noqa: E402
from agentkit import box  # noqa: E402

# The turn's command: a check it boxes writes HOME, then moves HOME, as a proof may, and writes
# Go's cache.
TURN = r'''import os, subprocess, sys
from agentkit import box
out, work = sys.argv[1:]
os.mkdir(out)
check = 'echo check > "$HOME/check-write" && HOME=/var/tmp && echo built > "$GOCACHE/entry"'
with box.command(["sh", "-c", check], dict(os.environ), out, cwd=work,
                 home_overlay=True) as (cmd, env, spawn):
    sys.exit(subprocess.run(cmd, env=env, cwd=work, timeout=60,
                            pass_fds=spawn["pass_fds"]).returncode)
'''


class GoCache(unittest.TestCase):
    def test_a_check_in_a_turn_writes_the_accounts_cache_and_its_home_for_nothing(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-box-go-cache-", dir=REPO) as tmp:
            home, work, out = (Path(tmp, name) for name in ("home", "work", "out"))
            for path in (home, work, out):
                path.mkdir()
            env = {key: value for key, value in os.environ.items()
                   if key not in ("GOCACHE", "GOENV", "XDG_CACHE_HOME", "XDG_CONFIG_HOME")}
            env.update(HOME=str(home), GOTOOLCHAIN="local", PYTHONPATH=str(REPO))
            # under HOME, where a mount of it would leave the check's HOME read-only
            cache = home / "acme-go-build"
            subprocess.run(["go", "env", "-w", f"GOCACHE={cache}"], env=env, cwd=tmp, check=True)
            with account_home(home), box.command(
                    [sys.executable, "-B", "-c", TURN, str(out / "check"), str(work)], env, out,
                    cwd=work) as (cmd, env, spawn):
                result = subprocess.run(cmd, env=env, cwd=work, capture_output=True, text=True,
                                        timeout=120, pass_fds=spawn["pass_fds"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((cache / "entry").read_text(), "built\n")
            self.assertFalse((home / "check-write").exists())


if __name__ == "__main__":
    unittest.main()
