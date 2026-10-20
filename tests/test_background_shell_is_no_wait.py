"""A background shell command is no wait: a Stop on it alone is judged as any other.

The host's rule: a seat waits through `ak wait`, never a Claude Code background command, which
the harness kills under memory pressure.  Offline: hooks/orchestrator-stop.sh is run as Claude
Code runs it, on the captured payload in tests/fixtures/claude-stop-background.json, in a
throwaway HOME whose seat owes an open plan line and waits on nothing else.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT = "acme-seat"
PAYLOAD = json.loads((REPO / "tests/fixtures/claude-stop-background.json").read_text())
SHELL, AGENT = PAYLOAD["background_tasks"]


class BackgroundShellIsNoWait(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-background-shell-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        state = self.home / ".agentkit/state"
        state.mkdir(parents=True)
        (state / f"stop-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "turn": time.time() - 60, "blocks": 0}) + "\n")
        (state / f"plan-{SEAT}.md").write_text(
            "- [ ] the parser parses · check: `false` · acme · written 2026-10-20 12:00\n")

    def stop(self, *tasks):
        payload = {**PAYLOAD, "transcript_path": "", "background_tasks": list(tasks)}
        done = subprocess.run(
            ["bash", str(HOOK)], input=json.dumps(payload), text=True, capture_output=True,
            timeout=30, env={"PATH": os.environ["PATH"], "HOME": str(self.home),
                             "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_a_shell_alone_is_held_and_told_to_ak_wait(self):
        self.assertEqual(SHELL["type"], "shell")
        decision = json.loads(self.stop(SHELL))
        self.assertEqual(decision["decision"], "block")
        self.assertIn("background command is no wait", decision["reason"])
        self.assertIn("ak wait <PR url or run id>", decision["reason"])

    def test_a_subagent_alone_stands(self):
        self.assertEqual(AGENT["type"], "subagent")
        self.assertEqual(self.stop(AGENT), "")


if __name__ == "__main__":
    unittest.main()
