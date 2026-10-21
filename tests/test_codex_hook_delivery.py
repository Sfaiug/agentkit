"""Ordinary tools do not wait for AK's observer or import its screen machinery.

The launch flags are the ones the real harness consumes. The cold subprocess pins the
hot path separately: a working seat has nothing new to record after an ordinary call.
"""
import json
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


class Delivery(unittest.TestCase):
    def launch(self, root):
        executable = root / "codex"
        executable.write_text("#!/bin/sh\necho ' --dangerously-bypass-hook-trust'\n")
        executable.chmod(0o755)
        seen = []
        with patch.dict(os.environ, {"HOME": str(root),
                                     codex.RECEIPT_ENV: str(root / "receipt")}):
            codex.main(["--", str(executable)], launch=lambda cmd, _: seen.append(cmd) or 0)
        flags = [seen[0][i + 1] for i, word in enumerate(seen[0]) if word == "-c"]
        hooks = {}
        for flag in flags:
            hooks.update(tomllib.loads(flag).get("hooks", {}))
        return hooks

    def test_an_observer_never_holds_an_ordinary_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            hooks = self.launch(Path(tmp))
        for event in ("PostToolUse",):
            with self.subTest(event=event):
                self.assertTrue(all(h.get("async") for g in hooks[event] for h in g["hooks"]))
        # Decisions and prompt context still arrive before the harness proceeds.
        for event in ("Stop", "PreToolUse", "UserPromptSubmit", "SessionStart",
                      "PermissionRequest", "Interrupt"):
            self.assertTrue(all(not h.get("async") for g in hooks[event] for h in g["hooks"]))

    def test_only_an_interrupt_uses_the_harness_interrupt_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            hooks = self.launch(Path(tmp))
        for event, groups in hooks.items():
            if event == "state":
                continue
            for group in groups:
                for handler in group["hooks"]:
                    with self.subTest(event=event, command=handler["command"]):
                        # Codex's documented default for command hooks is 600 seconds;
                        # Interrupt alone is capped at three. A busy host must not lose
                        # prompt or stop decisions to that unrelated interruption cap.
                        self.assertEqual(handler.get("timeout", 600),
                                         3 if event == "Interrupt" else 600)

    def test_an_ordinary_call_needs_no_display_or_notification_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = home / ".agentkit/state"
            state.mkdir(parents=True)
            fact = {"event": "UserPromptSubmit", "at": 100, "session": "acme"}
            (state / "hook-acme.json").write_text(json.dumps(fact))
            script = '''
import importlib.abc, io, runpy, sys
class NoScreen(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ("agentkit.watch", "agentkit.menu", "agentkit.notify"):
            raise ImportError("ordinary tools must not start " + fullname)
sys.meta_path.insert(0, NoScreen())
sys.argv = [sys.argv[1], "answered"]
sys.stdin = io.StringIO('{"hook_event_name":"PostToolUse","tool_name":"Bash"}')
runpy.run_path(sys.argv[0], run_name="__main__")
'''
            done = subprocess.run([sys.executable, "-B", "-c", script,
                                   str(REPO / "tools/codex-seat.py")],
                                  env={"HOME": tmp, "PATH": os.environ["PATH"],
                                       "AGENTKIT_SESSION": "acme"},
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, "")
            self.assertEqual(json.loads((state / "hook-acme.json").read_text()), fact)


if __name__ == "__main__":
    unittest.main()
