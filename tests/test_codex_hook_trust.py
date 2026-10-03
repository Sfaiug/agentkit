"""A Codex seat trusts exactly the hooks it installs, so it never stops on "Hooks need review"."""

import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit.harness import codex

# What codex-cli 0.160.0's app server answered `hooks/list` with (`key`, `currentHash`) for
# these hooks given on its command line, captured 3 Oct 2026.
HOOKS = {"SessionStart": [("/usr/bin/python3 /repo/tools/codex-seat.py capture", 5)],
         "UserPromptSubmit": [("bash /repo/hooks/seat-state.sh", 3)],
         "Stop": [("bash /repo/hooks/seat-state.sh", 3), ("bash /repo/hooks/orchestrator-stop.sh", 3)]}
CODEX = {
    "session_start:0:0": "08f3e8f2cf105abfedf19931921aab34f2c1d1e689099aa7b0e73d76faa9fe92",
    "user_prompt_submit:0:0": "fd11767f233eef29de09af33ade4aadd852035d57078db2319e5a2b994794e35",
    "stop:0:0": "486f75f24bc0da1bd386ebd1ee5d9ac9289f6d59faabd6ff9d431b4edf2f8275",
    "stop:0:1": "8685042ddef8d1705a49c9fc70344cf5a085f538ec4e4f52502081cb01a883d2"}


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
        self.assertEqual(len(installed), 5, installed)
        self.assertEqual(trusted, [codex.trust(installed)])


if __name__ == "__main__":
    unittest.main()
