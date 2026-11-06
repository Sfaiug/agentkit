"""Every box writes Go's build cache in the account's home, a turn's too, though its HOME is
read-only (tests/test_key_a_turn_builds_go.py), so what one box compiled serves the next."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]
from fixtures.sandbox import account_home  # noqa: E402
from agentkit import box  # noqa: E402


class GoCache(unittest.TestCase):
    def test_a_check_keeps_the_homes_cache(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-box-go-cache-", dir=REPO) as tmp:
            home = Path(tmp)
            (home / "out").mkdir()
            (home / "workspace").mkdir()
            env = {key: value for key, value in os.environ.items()
                   if key not in ("GOCACHE", "XDG_CACHE_HOME")}
            env.update(HOME=tmp, GOTOOLCHAIN="local")
            with patch.dict(os.environ, {"HOME": tmp}), account_home(home), box.command(
                    ["go", "env", "GOCACHE"], env, home / "out", cwd=home / "workspace",
                    home_overlay=True) as (cmd, env, spawn):
                result = subprocess.run(cmd, env=env, cwd=home / "workspace", capture_output=True,
                                        text=True, timeout=120, pass_fds=spawn["pass_fds"])
        self.assertEqual((result.returncode, result.stdout.strip()),
                         (0, str(home / ".cache/go-build")), result.stderr)


    def test_what_a_box_compiles_stays_for_the_next(self):
        for overlay in (False, True):
            with self.subTest(home_overlay=overlay), tempfile.TemporaryDirectory(
                    prefix=".ak-test-box-go-cache-", dir=REPO) as tmp:
                home = Path(tmp)
                (home / "out").mkdir()
                (home / "workspace").mkdir()
                env = {key: value for key, value in os.environ.items()
                       if key not in ("GOCACHE", "XDG_CACHE_HOME")}
                env.update(HOME=tmp)
                # a proof that moves HOME, as a manual run does, keeps the account's cache
                write = 'HOME="$TMPDIR"; echo "$GOCACHE"; echo built > "$GOCACHE/entry"'
                with patch.dict(os.environ, {"HOME": tmp}), account_home(home), box.command(
                        ["sh", "-c", write], env, home / "out", cwd=home / "workspace",
                        home_overlay=overlay) as (cmd, env, spawn):
                    result = subprocess.run(cmd, env=env, cwd=home / "workspace",
                                            capture_output=True, text=True, timeout=120,
                                            pass_fds=spawn["pass_fds"])
                self.assertEqual((result.returncode, result.stdout.strip()),
                                 (0, str(home / ".cache/go-build")), result.stderr)
                self.assertEqual((home / ".cache/go-build/entry").read_text(), "built\n")


if __name__ == "__main__":
    unittest.main()
