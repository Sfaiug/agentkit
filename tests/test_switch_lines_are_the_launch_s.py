"""A seat moved in place is typed the model and effort its harness's own launch is handed for
the same entry, so a switch and a restart land it alike: each `[switch]` in adapters/*.toml,
read by orch.switch_lines, against the line that harness's `interactive` prints.  OpenCode's
launch hands its TUI `<model>#<effort>` in a config document, the run its seat plugin's
`/ak-model` makes of the two (tests/test_opencode_seat_switches_model.py), and defines a few
variants itself, which only a launch can run: a move to one restarts, as does a move to a model
whose launch names none (`default`), which no line can name.

Offline: the real adapters, run against a temporary HOME with a fake harness binary on PATH,
and the seat's pane faked live.
"""

import json
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

    def launch(self, harness, effort, model="test-model"):
        """The words of `harness`'s `interactive` line for `model` at `effort`."""
        proc = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "interactive",
                               model, effort], capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 0, f"{harness}: {proc.stderr}")
        return shlex.split(proc.stdout)

    def switch(self, harness, effort, model="test-model", provider="acme"):
        """The lines a live seat on another model of `harness`, on provider `acme`, is owed for
        `model` on `provider`."""
        cfg = {"providers": {"acme": {}, provider: {}}, "models": {
            name: {"harness": harness, "model": own, "effort": "low", "provider": on}
            for name, own, on in (("was", "old-model", "acme"), ("to", model, provider))}}
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: ""}), \
                patch.object(config, "session_records", return_value={"atoll": {
                    "orchestrator": "was"}}), patch.object(orch, "find", return_value=None), \
                patch.object(orch, "harness_pane", return_value="%7"), \
                patch.object(orch, "tmux_out", return_value=(0, "0")):
            return [owed["line"] for owed in orch.switch_lines(cfg, "atoll", "to", effort) or ()]

    def test_each_harness_s_switch_is_what_its_launch_is_handed(self):
        self.assertEqual({harness for harness, _ in SWITCH} | {"opencode"},
                         {harness for harness, data in config.manifests() if "switch" in data})
        for (harness, effort), (lines, run) in SWITCH.items():
            with self.subTest(harness=harness, effort=effort):
                self.assertEqual(self.switch(harness, effort), lines)
                words = self.launch(harness, effort)
                self.assertTrue(holds(words, run), words)

    def test_opencode_s_names_the_run_its_launch_is_handed_but_a_variant_it_defines(self):
        [content] = [word.partition("=")[2] for word in self.launch("opencode", "high", "acme/m")
                     if word.startswith("OPENCODE_CONFIG_CONTENT=")]
        self.assertEqual(json.loads(content)["model"], "acme/m#high")
        self.assertEqual(self.switch("opencode", "high", "acme/m"), ["/ak-model acme/m high"])
        self.assertEqual(self.switch("opencode", "none", "acme/m"), [])
        self.assertEqual(self.switch("opencode", "high", "mimo/m"), [])
        # one opencode.db holds every provider's login, so another provider's model is the same
        # process's to run; Codex launches each subscription on its own
        self.assertEqual(self.switch("opencode", "high", "beta/m", provider="beta"),
                         ["/ak-model beta/m high"])
        self.assertEqual(self.switch("codex", "high", provider="beta"), [])

    def test_a_model_its_harness_picks_itself_restarts(self):
        self.assertNotIn("-m", self.launch("codex", "high", model=config.DEFAULT_MODEL))
        self.assertEqual(self.switch("codex", "high", model=config.DEFAULT_MODEL), [])


if __name__ == "__main__":
    unittest.main()
