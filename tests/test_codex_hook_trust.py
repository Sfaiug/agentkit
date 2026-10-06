"""A Codex seat trusts exactly the hooks it installs, so it never stops on "Hooks need review"."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit.harness import codex

# What codex-cli 0.160.0's app server answered `hooks/list` with (`key`, `currentHash`) for
# these hooks given on its command line, captured 3 Oct 2026 (PreToolUse 6 Oct).
HOOKS = {"SessionStart": [("/usr/bin/python3 /repo/tools/codex-seat.py capture", 5)],
         "UserPromptSubmit": [("bash /repo/hooks/seat-state.sh", 3)],
         "Stop": [("bash /repo/hooks/seat-state.sh", 3), ("bash /repo/hooks/orchestrator-stop.sh", 3)],
         "Interrupt": [("bash /repo/hooks/seat-state.sh", 3)],
         "PermissionRequest": [("bash /repo/hooks/seat-state.sh", 3)],
         "PreToolUse": [("bash /repo/hooks/seat-guard.sh", 3)]}
CODEX = {
    "session_start:0:0": "08f3e8f2cf105abfedf19931921aab34f2c1d1e689099aa7b0e73d76faa9fe92",
    "user_prompt_submit:0:0": "fd11767f233eef29de09af33ade4aadd852035d57078db2319e5a2b994794e35",
    "stop:0:0": "486f75f24bc0da1bd386ebd1ee5d9ac9289f6d59faabd6ff9d431b4edf2f8275",
    "stop:0:1": "8685042ddef8d1705a49c9fc70344cf5a085f538ec4e4f52502081cb01a883d2",
    "interrupt:0:0": "e376187e62d824d7de00d343edc5f71df565877cf47c6f7c5547feb3dede8298",
    "permission_request:0:0": "99205413bb3bf695b0e8c4131068cc1fca5fac81fd9232fd5d0d308dfaa51edc",
    "pre_tool_use:0:0": "0a8f11c1538e76b9c84eddc50898abb03e967f2570bbb1252074e7806158514b"}


def state(flag):
    return {key.removeprefix("/<session-flags>/config.toml:"): value["trusted_hash"]
            .removeprefix("sha256:") for key, value in tomllib.loads(flag)["hooks"]["state"].items()}


class HookTrust(unittest.TestCase):
    def test_hashes_are_codexs_own(self):
        self.assertEqual(state(codex.trust(HOOKS)), CODEX)

    def test_seat_launch_trusts_exactly_its_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "codex"
            fake.write_text("#!/bin/sh\necho '  --dangerously-bypass-hook-trust'\n")
            fake.chmod(0o755)
            seen = []
            with patch.dict(os.environ, {codex.RECEIPT_ENV: str(Path(tmp) / "receipt")}):
                codex.main(["--", str(fake)], launch=lambda cmd, receipt: seen.append(cmd) or 0)
        flags = [seen[0][i + 1] for i, word in enumerate(seen[0]) if word == "-c"]
        installed = {}
        for flag in flags:
            hooks = tomllib.loads(flag).get("hooks", {})
            for event, groups in hooks.items():
                if event != "state":
                    self.assertEqual(len(groups), 1, flag)
                    installed[event] = [(h["command"], h["timeout"]) for h in groups[0]["hooks"]]
        trusted = [flag for flag in flags if flag.startswith("hooks.state=")]
        self.assertEqual(len(installed), 6, installed)
        self.assertEqual(sum(map(len, installed.values())), 7)
        self.assertEqual(installed["PreToolUse"], [(f"bash {REPO}/hooks/seat-guard.sh", 3)])
        self.assertEqual(trusted, [codex.trust(installed)])
        self.assertNotIn("--dangerously-bypass-hook-trust", seen[0])

    def test_fresh_home_fails_instead_of_declining_hook_review(self):
        source = (REPO / "tests/e2e-fresh.sh").read_text()
        driver = source.split("cat >\"$WORK/ptydrive.py\" <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        fake = ("import sys\n"
                "if sys.argv[1] == 'review':\n"
                "    print('Hooks need review\\n3. Continue without trusting', flush=True)\n"
                "    if input().strip() != '3': sys.exit(1)\n"
                "print('Ask Codex to do anything', flush=True)\n"
                "input()\n")
        with tempfile.TemporaryDirectory(prefix=".ak-test-", dir=REPO) as tmp:
            tmp = Path(tmp)
            (tmp / "driver.py").write_text(driver)
            (tmp / "steps").write_text("expect 2 Ask Codex to do anything\n")
            for screen, rc in (("prompt", 0), ("review", 1)):
                with self.subTest(screen=screen):
                    result = subprocess.run(
                        [sys.executable, str(tmp / "driver.py"), str(tmp / "screen"),
                         str(tmp / "steps"), "--", sys.executable, "-c", fake, screen],
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, rc, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
