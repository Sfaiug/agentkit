"""The same contract reaches every adapter, including one added after discovery."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SMOKE = (REPO / "tests/smoke.sh").read_text()


def between(start, end):
    return SMOKE[SMOKE.index(start):SMOKE.index(end, SMOKE.index(start))]


CHECK = ('. "$REPO/tests/acceptance.sh"\nak() { return 1; }\n'
         + between("model_unavailable()", "reprobe()")
         + between("newrepo()", 'echo "workdir:')
         + between("# --- 3:", "# --- 4:") + "finish\n")


class Contract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-contract-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home, self.adapters, self.bin = (self.root / p for p in ("home", "adapters", "bin"))
        for path in (self.home, self.adapters, self.bin):
            path.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        for tool in ("bash", "git", "mkdir", "cat", "grep", "head", "tail", "sed", "date"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        (self.bin / "echo").touch(mode=0o755)
        self.env = {"HOME": str(self.home), "PATH": str(self.bin), "WORK": str(self.root),
                    "REPO": str(REPO), "SMOKE_CALLER_HOME": str(self.home),
                    "AGENTKIT_ADAPTER_DIR": str(self.adapters), "AK_RUN_DEPTH": "0",
                    "AK_MAX_RUNS": "0", "PYTHONDONTWRITEBYTECODE": "1",
                    "AGENTKIT_DISCORD_WEBHOOK": "off", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1"}

    def adapter(self, name, script=None):
        fixture = REPO / "tests/fixtures/adapters"
        shutil.copy2(fixture / "echo.toml", self.adapters / f"{name}.toml")
        path = self.adapters / f"{name}.sh"
        path.write_text(script or (fixture / "echo.sh").read_text())
        path.chmod(0o755)

    def gate(self):
        return subprocess.run(["/bin/bash", "-c", "set -uo pipefail\n" + CHECK],
                              cwd=self.root, env=self.env, text=True,
                              capture_output=True, timeout=30)

    def test_a_turn_that_never_hands_in_fails(self):
        # The old word-only path passes this adapter even though no worker can close a turn.
        self.adapter("opencode", '''#!/bin/bash
case $1 in
  auth) echo 'fixture: logged in' ;;
  run) mkdir -p "$6"; echo hello >"$4/hello.txt"
       echo PONG >"$6/final.md"; echo fixture-session >"$6/session_id" ;;
esac
''')
        (self.bin / "opencode").touch(mode=0o755)
        result = self.gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("hand-in done", result.stdout)

    def test_echo_passes(self):
        self.adapter("echo")
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  3 echo:", result.stdout)
        self.assertIn("resumed", result.stdout)

    def test_an_adapter_added_to_the_directory_is_checked(self):
        self.adapter("echo")
        first = self.gate()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.adapter("acme")
        second = self.gate()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("PASS  3 acme:", second.stdout)
        self.assertIn("PASS  3 echo:", second.stdout)

    def standalone(self, *args):
        return subprocess.run([sys.executable, str(REPO / "tests/check_harness_contract.py"),
                               *args], cwd=self.root, env=self.env, text=True,
                              capture_output=True, timeout=30)

    def test_standalone_checks_all_or_one(self):
        self.adapter("echo")
        self.adapter("acme")
        all_harnesses = self.standalone()
        self.assertEqual(all_harnesses.returncode, 0, all_harnesses.stdout + all_harnesses.stderr)
        self.assertIn("2 passed, 0 failed, 0 skipped", all_harnesses.stdout)
        one = self.standalone("echo")
        self.assertEqual(one.returncode, 0, one.stdout + one.stderr)
        self.assertIn("PASS  3 echo:", one.stdout)
        self.assertNotIn("acme", one.stdout)

    def test_no_harness_installed_fails(self):
        result = self.standalone()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("no harness here is installed with its login", result.stdout)

    def test_a_turn_without_a_session_id_fails(self):
        fixture = (REPO / "tests/fixtures/adapters/echo.sh").read_text()
        self.adapter("echo", fixture.replace("printf 'echo:%s\\n' \"$filename\"", ":"))
        result = self.standalone()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("no session_id", result.stdout)

    def test_a_session_that_forgets_the_file_fails(self):
        fixture = (REPO / "tests/fixtures/adapters/echo.sh").read_text()
        self.adapter("echo", fixture.replace('"${7#echo:}"', '"forgot"'))
        result = self.standalone()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL  3 echo: resume", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
