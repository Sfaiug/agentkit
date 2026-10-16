"""Guard imports must not change the environment of a seat's commands or their Python children.

Offline: every real command is a Python stand-in importing a sibling in a temporary HOME.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
TOOLS = ("git", "gh", "tmux", "scp", "rsync", "sftp")
KEYS = ("PYTHONSAFEPATH", "PYTHONPATH")


class ShimEnvironment(unittest.TestCase):
    def test_commands_keep_the_callers_environment_even_if_the_guard_cannot_import(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-shim-env-", dir=REPO) as tmp:
            root = Path(tmp)
            shims, real = root / "bin", root / "real"
            shims.mkdir()
            real.mkdir()
            (real / "sibling.py").write_text("VALUE = 7\n")
            script = (f"#!{sys.executable}\nimport json, os\nfrom sibling import VALUE\n"
                      f"print(json.dumps([VALUE, [os.environ.get(k) for k in {KEYS!r}]]))\n")
            for name in TOOLS:
                command = real / name
                command.write_text(script)
                command.chmod(0o755)
            broken = root / "broken"
            (broken / "tools").mkdir(parents=True)
            (broken / "tools/shim").write_bytes((REPO / "tools/shim").read_bytes())
            (broken / "tools/shim").chmod(0o755)
            (broken / "agentkit").mkdir()
            (broken / "agentkit/__init__.py").write_text("")
            (broken / "agentkit/guard.py").write_text("raise ImportError('broken')\n")
            for name in TOOLS:
                (broken / f"tools/{name}-shim").symlink_to("shim")
            env = {k: v for k, v in os.environ.items() if k not in KEYS}
            env.update(HOME=tmp, AGENTKIT_SESSION="acme", AK_RUN_ROLE="",
                       PATH=os.pathsep.join([str(shims), str(real), os.environ.get("PATH", "")]))
            for checkout in (REPO, broken):
                for name in TOOLS:
                    link = shims / name
                    link.unlink(missing_ok=True)
                    link.symlink_to(checkout / f"tools/{name}-shim")
                for overrides in ({}, dict.fromkeys(KEYS, ""),
                                  {"PYTHONSAFEPATH": "1", "PYTHONPATH": str(real)}):
                    for name in TOOLS:
                        with self.subTest(guard=checkout.name, tool=name, env=overrides):
                            result = subprocess.run([str(shims / name), "--version"], cwd=root,
                                                    env={**env, **overrides}, capture_output=True,
                                                    text=True, timeout=15)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(json.loads(result.stdout),
                                             [7, [overrides.get(key) for key in KEYS]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
