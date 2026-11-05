"""A worker turn builds Go in its box's own cache, its home read-only; a check keeps the home's."""

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
    def boxed(self, argv, **kwargs):
        with tempfile.TemporaryDirectory(prefix=".ak-test-box-go-cache-", dir=REPO) as tmp:
            home = Path(tmp)
            (home / "out").mkdir()
            (home / "workspace/p").mkdir(parents=True)
            (home / "workspace/go.mod").write_text("module acme\n\ngo 1.21\n")
            (home / "workspace/p/p.go").write_text("package p\n\nfunc F() int { return 1 }\n")
            env = {key: value for key, value in os.environ.items()
                   if key not in ("GOCACHE", "XDG_CACHE_HOME")}
            env.update(HOME=tmp, GOTOOLCHAIN="local", GOPROXY="off")
            with patch.dict(os.environ, {"HOME": tmp}), account_home(home), box.command(
                    argv, env, home / "out", cwd=home / "workspace", **kwargs) as (cmd, env, spawn):
                return subprocess.run(cmd, env=env, cwd=home / "workspace", capture_output=True,
                                      text=True, timeout=120, pass_fds=spawn["pass_fds"]), home

    def test_a_turn_builds_go(self):
        result, _ = self.boxed(["go", "build", "./p"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_check_keeps_the_homes_cache(self):
        result, home = self.boxed(["go", "env", "GOCACHE"], home_overlay=True)
        self.assertEqual((result.returncode, result.stdout.strip()),
                         (0, str(home / ".cache/go-build")), result.stderr)


if __name__ == "__main__":
    unittest.main()
