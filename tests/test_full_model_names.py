"""Every screen and a seat's bar name a model by its full name, version and all.

The owner (20 Oct 2026): "it should always be the full model name with the version. For example
gpt-6.1-sol or Opus 5.5", where screens said `gpt-sol` and `opus`, the short names the models
are configured under.  The full name is the harness's catalog label for the model's id, else
the id itself.  Offline: a temporary HOME, no tmux.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, statusbar  # noqa: E402

MODELS = {"opus": {"harness": "claude", "provider": "anthropic", "model": "claude-opus-5-5"},
          "gpt-sol": {"harness": "codex", "provider": "openai", "model": "gpt-6.1-sol"},
          "flash": {"harness": "opencode", "provider": "opencode",
                    "model": "opencode/acme-flash-free"},
          "codex": {"harness": "codex", "provider": "openai", "model": "default"}}


class FullNames(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.cfg = {"models": MODELS}

    def test_a_model_is_named_by_its_catalog_label_else_its_id(self):
        self.assertEqual([config.model_name(self.cfg, name) for name in MODELS],
                         ["Opus 5.5", "gpt-6.1-sol", "acme-flash-free", "codex"])
        self.assertEqual(config.model_name(self.cfg, "gone"), "gone")

    def test_a_seat_row_its_crew_and_its_bar_say_the_full_names(self):
        selection = {"orchestrator": "opus", "workers": ["gpt-sol"], "reviewers": ["opus"]}
        self.assertEqual(menu.seat_crew(self.cfg, selection), (["gpt-6.1-sol"], ["Opus 5.5"]))
        written = []
        with patch.object(statusbar, "_tell", lambda _target, options: written.extend(options)):
            statusbar._write("fix-api", "opus", "working", cfg=self.cfg)
        top = next(value for _target, option, value in written if option == statusbar.TOPS[0])
        self.assertIn("Opus 5.5", top)
        self.assertNotIn("opus", top.replace("Opus", ""))


if __name__ == "__main__":
    unittest.main()
