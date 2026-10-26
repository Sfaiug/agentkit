"""A seat's record from before, or a model it falls back on, holds the efforts the entries gave
it: before a config save changes them, the shipped config's for a file with no model tables,
and at the read that falls back.  Offline, in a throwaway HOME."""

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
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"HOME": tmp.name, "AGENTKIT_SESSION": ""}))
        home = Path(tmp.name) / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        config.ensure_dirs()
        self.config = home / config.CONFIG_NAME
        self.record = config.session_path("acme")

    def test_a_save_on_the_shipped_entries(self):
        self.config.write_text("max_runs = 2\n")
        cfg = config.load()
        self.record.write_text(json.dumps({"orchestrator": "fable", "workers": ["fable"]}))
        cfg["models"]["fable"]["effort"] = "low"
        config.save(cfg)
        self.assertEqual(json.loads(self.record.read_text())["efforts"],
                         {"fable": {"effort": "xhigh"}})

    def test_a_read_falling_back_on_a_worker(self):
        self.config.write_text("max_runs = 2\n")
        self.record.write_text(json.dumps({"orchestrator": "astra", "workers": ["gone"],
                                           "efforts": {"astra": {"effort": "low"}}}))
        self.assertEqual(config.load_session(config.load(), "acme")["workers"], ["fable"])
        self.assertEqual(json.loads(self.record.read_text())["efforts"]["fable"],
                         {"effort": "xhigh"})


if __name__ == "__main__":
    unittest.main()
