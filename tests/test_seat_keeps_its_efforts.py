"""Before a config save changes the entries, a seat's record from before, and a worker it falls
back on, holds the efforts they gave it, the shipped config's for a file with no model tables;
a read writes nothing.  Offline, in a throwaway HOME."""

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

    def test_a_save_on_the_file_s_entries_or_the_shipped_ones(self):
        shipped = config.REPO.joinpath(config.DEFAULT_CONFIG_NAME).read_text()
        fable = shipped.replace('effort = "xhigh"', 'effort = "high"', 1)    # its first model
        for text, effort in ((fable, "high"), ("max_runs = 2\n", "xhigh")):
            self.config.write_text(text)
            cfg = config.load()
            self.record.write_text(json.dumps({"orchestrator": "fable", "workers": ["fable"]}))
            cfg["models"]["fable"]["effort"] = "low"
            config.save(cfg)
            self.assertEqual(json.loads(self.record.read_text())["efforts"],
                             {"fable": {"effort": effort}})

    def test_a_save_on_a_worker_fallen_back_on(self):
        self.config.write_text("max_runs = 2\n")
        self.record.write_text(json.dumps({"orchestrator": "astra", "workers": ["gone"],
                                           "efforts": {"astra": {"effort": "low"}}}))
        cfg, before = config.load(), self.record.read_bytes()
        self.assertEqual(config.load_session(cfg, "acme")["efforts"]["fable"], {"effort": "xhigh"})
        self.assertEqual(self.record.read_bytes(), before)
        cfg["models"]["fable"]["effort"] = "low"
        config.save(cfg)
        self.assertEqual(json.loads(self.record.read_text())["efforts"]["fable"],
                         {"effort": "xhigh"})


if __name__ == "__main__":
    unittest.main()
