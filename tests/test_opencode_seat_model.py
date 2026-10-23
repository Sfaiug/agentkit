"""The primary agent of a new OpenCode seat receives the selected model and variant."""

import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class OpenCodeSeatModel(unittest.TestCase):
    def test_the_primary_agent_receives_the_chosen_model_and_variant(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            binary = home / "opencode"
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            rules = home / "rules.md"
            rules.write_text("Follow the task.\n")
            env = {"HOME": str(home), "PATH": f"{home}:/usr/bin:/bin",
                   "AGENTKIT_RULEBOOK": str(rules)}
            for model, effort, expected in (("acme/flash", "max", "acme/flash#max"),
                                            ("acme/flash#low", "high", "acme/flash#low")):
                with self.subTest(model=model, effort=effort):
                    made = subprocess.run([str(REPO / "adapters/opencode.sh"), "interactive",
                                           model, effort], env=env, capture_output=True,
                                          text=True, timeout=10)
                    self.assertEqual(made.returncode, 0, made.stderr)
                    content = next(word.split("=", 1)[1] for word in shlex.split(made.stdout)
                                   if word.startswith("OPENCODE_CONFIG_CONTENT="))
                    agent = json.loads(content)["agents"]["build"]
                    self.assertEqual(agent.get("model"), expected)


if __name__ == "__main__":
    unittest.main()
