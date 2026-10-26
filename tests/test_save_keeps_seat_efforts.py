"""A config save first leaves every seat holding the efforts the entries gave it.  Offline.

A record from before efforts lived on records, which nothing has read yet, keeps the effort
its entry had before the save changed it: the file's own entry, and the shipped config's where
the file has no model tables.  A throwaway HOME holds the config and the records.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config


class SaveKeepsSeatEfforts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".efforts-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"HOME": str(root), "AGENTKIT_SESSION": ""}))
        home = root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        config.ensure_dirs()
        self.config = home / config.CONFIG_NAME
        self.record = config.session_path("acme")

    def saved(self):
        """The record's efforts once Fable's entry is saved at `low`, its record from before."""
        cfg = config.load()
        self.record.write_text(json.dumps({"orchestrator": "fable", "workers": ["fable"]}))
        cfg["models"]["fable"]["effort"] = "low"
        config.save(cfg)
        self.assertEqual(config.load()["models"]["fable"]["effort"], "low")
        return json.loads(self.record.read_text())["efforts"]

    def test_the_file_s_entry(self):
        self.config.write_text(config.REPO.joinpath(config.DEFAULT_CONFIG_NAME).read_text()
                               .replace('model = "claude-fable-5-1"\neffort = "xhigh"',
                                        'model = "claude-fable-5-1"\neffort = "high"'))
        self.assertEqual(self.saved(), {"fable": {"effort": "high"}})

    def test_the_shipped_entry_for_a_file_with_no_model_tables(self):
        self.config.write_text("max_runs = 2\n")
        self.assertEqual(self.saved(), {"fable": {"effort": "xhigh"}})


if __name__ == "__main__":
    unittest.main()
