"""A seat moved in place is typed the model and effort its harness's own launch is handed for
the same entry, so a switch and a restart land it alike: each `[switch]` in adapters/*.toml,
read by orch.switch_lines, against the line that harness's `interactive` prints.  OpenCode,
whose TUI takes a model only in its dialogs, has none and restarts.

Offline: the real adapters, run against a temporary HOME with a fake harness binary on PATH,
and the seat's pane faked live.
"""

import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch

# What each harness's prompt is typed to run `test-model` at an effort, and the words its launch
# is handed for the same.  agy's `/model` takes the base model and `/effort` picks its variant,
# the full id it launches on; a model it runs at no effort is that id itself.
SWITCH = {("claude", "high"): (["/model test-model", "/effort high"],
                               ["--model", "test-model", "--effort", "high"]),
          ("codex", "high"): (["/model test-model --reasoning=high"],
                              ["-m", "test-model", "-c", 'model_reasoning_effort="high"']),
          ("muse", "high"): (["/model test-model", "/effort high"],
                             ["--model", "test-model", "--reasoning-effort", "high"]),
          ("grokbuild", "high"): (["/model test-model", "/effort high"],
                                  ["--model", "test-model", "--reasoning-effort", "high"]),
          ("antigravity", "high"): (["/model test-model", "/effort high"],
                                    ["--model", "test-model-high"]),
          ("antigravity", "none"): (["/model test-model"], ["--model", "test-model"])}


def holds(words, run):
    return any(words[at:at + len(run)] == run for at in range(len(words)))


class SwitchLinesAreTheLaunchS(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-switch-lines-")
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        fakes = home / "bin"
        fakes.mkdir()
        (fakes / "harness").write_text("#!/bin/sh\nexit 0\n")
        (fakes / "harness").chmod(0o755)
        for _, data in config.manifests():
            (fakes / data["update"]["version"][0]).symlink_to("harness")
        rulebook = home / ".agentkit/state/rulebook-atoll.md"
        rulebook.parent.mkdir(parents=True)
        rulebook.write_text("# rules\n")
        drop = {config.ACCOUNT_ENV, config.ADAPTER_DIR_ENV, "AGENTKIT_FIRST_PROMPT",
                "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME"}
        self.env = {**{k: v for k, v in os.environ.items() if k not in drop},
                    "HOME": str(home), "PATH": f"{fakes}:{os.environ['PATH']}",
                    "AGENTKIT_SESSION": "atoll", config.RULEBOOK_ENV: str(rulebook),
                    "AGENTKIT_CLAUDE_CHECKED": "1"}

    def launch(self, harness, effort):
        """The words of `harness`'s `interactive` line for `test-model` at `effort`."""
        proc = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "interactive",
                               "test-model", effort], capture_output=True, text=True,
                              env=self.env)
        self.assertEqual(proc.returncode, 0, f"{harness}: {proc.stderr}")
        return shlex.split(proc.stdout)

    def switch(self, harness, effort):
        """The lines a live seat on another model of `harness` is owed for `test-model`."""
        cfg = {"providers": {"acme": {}}, "models": {
            name: {"harness": harness, "model": model, "effort": "low", "provider": "acme"}
            for name, model in (("was", "old-model"), ("to", "test-model"))}}
        with patch.object(config, "session_records", return_value={"atoll": {
                "orchestrator": "was"}}), patch.object(orch, "find", return_value=None), \
                patch.object(orch, "harness_pane", return_value="%7"), \
                patch.object(orch, "tmux_out", return_value=(0, "0")):
            return [owed["line"] for owed in orch.switch_lines(cfg, "atoll", "to", effort) or ()]

    def test_each_harness_s_switch_is_what_its_launch_is_handed(self):
        self.assertEqual({harness for harness, _ in SWITCH},
                         {harness for harness, data in config.manifests() if "switch" in data})
        for (harness, effort), (lines, run) in SWITCH.items():
            with self.subTest(harness=harness, effort=effort):
                self.assertEqual(self.switch(harness, effort), lines)
                words = self.launch(harness, effort)
                self.assertTrue(holds(words, run), words)


if __name__ == "__main__":
    unittest.main()
