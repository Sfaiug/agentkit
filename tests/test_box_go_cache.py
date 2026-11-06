"""A check's box keeps Go's build cache in its home, where a turn's box has one of its own
(tests/test_key_a_turn_builds_go.py)."""

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


if __name__ == "__main__":
    unittest.main()
