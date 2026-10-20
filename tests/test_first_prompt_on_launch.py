"""A seat's launch can carry its first message.

Every adapter whose manifest says `[launch] first_prompt = true` puts $AGENTKIT_FIRST_PROMPT on
the `interactive` line as its harness's own first prompt, one word whatever quotes, newlines
or `$` it holds, and no option even when it starts with `-`, for a new conversation and a
resumed one; every other adapter prints the same line with it as without.  The loop reads
`adapters/*.toml`, so a harness added later is covered.

Offline: the real adapters, run against a temporary HOME with a fake harness binary on PATH.
"""

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config

TEXT = 'say "hi" $HOME'
DASHED = "--help"


class FirstPromptOnLaunch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-first-prompt-")
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
                "AGENTKIT_TMUX_SOCKET", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                "GROK_HOME"}
        self.env = {**{k: v for k, v in os.environ.items() if k not in drop},
                    "HOME": str(home), "PATH": f"{fakes}:{os.environ['PATH']}",
                    "AGENTKIT_SESSION": "atoll", config.RULEBOOK_ENV: str(rulebook),
                    "AGENTKIT_CLAUDE_CHECKED": "1"}

    def line(self, harness, conversation, **env):
        """The words of `harness`'s `interactive` line, as `ak orch` splits them."""
        proc = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "interactive",
                               "test-model", "high", *conversation],
                              capture_output=True, text=True, env={**self.env, **env})
        self.assertEqual(proc.returncode, 0, f"{harness}: {proc.stderr}")
        return shlex.split(proc.stdout)

    def test_each_adapter_takes_the_first_prompt_its_manifest_declares(self):
        for harness, data in config.manifests():
            honours = (data.get("launch") or {}).get("first_prompt") is True
            for conversation, text in (([], TEXT), (["0d5f3c1e-6b1a-4c55-9f0e-2a7d8e4b9c10"], TEXT),
                                       ([], DASHED)):
                with self.subTest(harness=harness, resumed=bool(conversation), text=text):
                    plain = self.line(harness, conversation)
                    given = self.line(harness, conversation, AGENTKIT_FIRST_PROMPT=text)
                    if honours:
                        # the last word, after the `--` that ends the options or as a flag's
                        # `=` value, so a message starting with `-` is never read as an option
                        self.assertTrue(given[-2:] == ["--", text] or
                                        re.fullmatch(r"--[\w-]+=" + re.escape(text), given[-1]),
                                        given[-2:])
                    else:
                        self.assertEqual(given, plain)
                    # an empty one adds no word (Antigravity's line names a fresh directory
                    # each launch, so the words themselves differ)
                    empty = self.line(harness, conversation, AGENTKIT_FIRST_PROMPT="")
                    self.assertEqual(len(empty), len(plain))

    def test_claude_and_codex_declare_it(self):
        for harness in ("claude", "codex"):
            self.assertIs(config.manifest(harness)["launch"]["first_prompt"], True, harness)


if __name__ == "__main__":
    unittest.main()
