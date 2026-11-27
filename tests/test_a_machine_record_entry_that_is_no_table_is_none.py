"""A machines record entry that is not a table is no record of that machine, and a last answer
that is not one is none: such a listed machine is still a helper and takes what one not answered
yet takes, tests alone, beside one whose answer reads as an always-on Linux machine's."""

import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, machines

SAID = {"system": "Linux", "processor": "arm64", "cores": 4, "memory_mb": 8192, "free_mb": 6144,
        "load": 1, "disk_free_mb": 102400, "battery": 0, "power": 1}


class AnEntryThatIsNoTableIsNone(unittest.TestCase):
    def test_each_listed_machine_takes_its_work_whatever_its_entry_holds(self):
        with Home() as home:
            akconfig.write(home, ["fable"], extra="".join(
                f"[machines.{name}]\n" for name in ("acme-null", "acme-word", "acme-box")))
            at = time.time()
            home.write(".agentkit/state/machines.json", {
                "acme-null": None, "acme-word": {"checks": [[at, True]], "said": "acme"},
                "acme-box": {"checks": [[at, True]], "said": {**SAID, "at": at}}})
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True):
                self.assertEqual([(name, machines.work(name)) for name in machines.helpers()],
                                 [("acme-null", ["tests"]), ("acme-word", ["tests"]),
                                  ("acme-box", ["turns", "tests"])])


if __name__ == "__main__":
    unittest.main()
