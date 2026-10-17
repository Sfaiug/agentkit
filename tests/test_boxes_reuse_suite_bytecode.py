"""A Python a check box starts during the suite imports agentkit from the suite's bytecode.

tests/every_file.py runs a stand-in test file in a temporary checkout, with the real per-file
environment. That file compiles agentkit outside a box and then imports it again inside one.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

FIXTURE = '''import importlib, os, subprocess, sys
from pathlib import Path
repo = REPO
sys.path.insert(0, repo)
# The test file's own import writes the suite's bytecode, outside any box.
worker = importlib.import_module("agentkit.worker")
activity = Path(os.environ["HOME"], "check.log")
with activity.open("w+b") as output:
    code, _, killed = worker.boxed(
        [sys.executable, "-v", "-c", "import agentkit.worker"], 60, env=dict(os.environ),
        cwd=repo, activity=activity, output=output, stderr=subprocess.STDOUT)
    output.seek(0)
    imports = output.read().decode(errors="replace")
source = os.path.join(repo, "agentkit", "")
# Python names the .py it compiled a module from, and the .pyc it found matching instead.
compiled = [line for line in imports.splitlines() if line.startswith("# code object from " + source)]
assert (code, killed) == (0, False), imports[-3000:]
assert not compiled, compiled
assert f".pyc matches {source}worker.py" in imports, imports[-3000:]
print("TESTS_RUN=1")
'''


class BoxesReuseSuiteBytecode(unittest.TestCase):
    def test_boxed_python_imports_agentkit_from_bytecode_compiled_before_the_box(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-box-bytecode-", dir=REPO) as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests/smoke.sh").write_text("")
            (root / "tests/test_acme.py").write_text(FIXTURE.replace("REPO", repr(str(REPO)), 1))
            env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_"))}
            env.update(HOME=tmp, PYTHONDONTWRITEBYTECODE="",
                       AK_HOST_READINGS='{"cpus": 2, "load": 0, "cpu_pressure": 12, "free_mb": 4096}')
            proc = subprocess.run([sys.executable, str(REPO / "tests/every_file.py"), tmp],
                                  env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS  tests/test_acme.py", proc.stdout)


if __name__ == "__main__":
    unittest.main()
