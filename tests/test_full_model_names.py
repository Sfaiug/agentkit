"""Every screen and a seat's bar name a model by its full name, version and all.

The owner (20 Oct 2026): "it should always be the full model name with the version. For example
gpt-6.1-sol or Opus 5.5", where screens said `gpt-sol` and `opus`, the short names the models
are configured under.  The full name is the harness's catalog label for the model's id, else
its name and number read off that id (config.model_label).  Offline: a temporary HOME, no tmux.
"""

import json
import os
import re
import sys
import tomllib
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

    def test_a_model_is_named_by_its_catalog_label_else_off_its_id(self):
        self.assertEqual([config.model_name(self.cfg, name) for name in MODELS],
                         ["Opus 5.5", "6.1 Sol", "Acme Flash Free", "codex"])
        self.assertEqual(config.model_name(self.cfg, "gone"), "gone")

    def test_a_label_the_table_gives_wins_even_where_it_is_the_id_itself(self):
        # only a row the table gives no label is named off its id
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.toml").write_text('family = "Acme"\n[catalog]\n'
                                            '"acme-nova-7-1" = { label = "acme-nova-7-1" }\n'
                                            '"acme-nova-7-2" = {}\n')
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        cfg = {"models": {n: {"harness": "acme", "model": f"acme-nova-7-{n}"} for n in "12"}}
        self.assertEqual([config.model_name(cfg, n) for n in "12"], ["acme-nova-7-1", "Nova 7.2"])
        self.assertEqual([model["label"] for model in config.catalog_held("acme")],
                         ["acme-nova-7-1", "Nova 7.2"])

    def test_a_shipped_label_says_only_what_the_name_off_its_id_cannot_and_no_family_word(self):
        # the owner (10 Nov 2026): "Even for sol, I want it to be 6.1 Sol max from now on, no
        # more GPT": a row whose label the rule says, or says with the maker's word, has none
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        for path in sorted((config.REPO / "adapters").glob("*.toml")):
            shipped = tomllib.loads(path.read_text())
            family = shipped.get("family", "")
            (adapters / path.name).write_text(f"family = {json.dumps(family)}\n")  # no table
            for model, entry in shipped.get("catalog", {}).items():
                with self.subTest(harness=path.stem, model=model):
                    label = entry.get("label")
                    self.assertNotEqual(label, config.model_label(path.stem, model))
                    self.assertFalse(label and family and re.match(rf"{re.escape(family)}\b",
                                                                   label, re.I), label)

    def test_a_seat_row_its_crew_and_its_bar_say_the_full_names(self):
        selection = {"orchestrator": "opus", "workers": ["gpt-sol"], "reviewers": ["opus"]}
        self.assertEqual(menu.seat_crew(self.cfg, selection),
                         ("Opus 5.5", ["6.1 Sol"], ["Opus 5.5"]))
        written = []
        with patch.object(statusbar, "_tell", lambda _target, options: written.extend(options)):
            statusbar._write("fix-api", "opus", "working", cfg=self.cfg)
        top = next(value for _target, option, value in written if option == statusbar.TOPS[0])
        self.assertIn("Opus 5.5", top)
        self.assertNotIn("opus", top.replace("Opus", ""))


if __name__ == "__main__":
    unittest.main()
