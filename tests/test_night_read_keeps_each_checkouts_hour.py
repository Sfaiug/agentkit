"""A slow night read shortens no later checkout's hour, whichever checkout it is."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, nightly


class EachCheckoutsHour(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "state").mkdir()
        self.now, self.reads, self.slow = 100000.0, [], nightly.CEILING
        checkouts = [root / "acme", root / "zen"]
        for patcher in (patch.object(config, "HOME", root),
                        patch.object(nightly, "time", SimpleNamespace(time=lambda: self.now)),
                        patch.object(nightly.orch, "checkouts", return_value=checkouts),
                        patch.object(nightly, "_read", side_effect=self.read)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def read(self, checkout, handled, log):
        """The very first read of all is the slow one."""
        self.reads.append(checkout.name)
        self.now += self.slow
        self.slow = 0

    def tick_at(self, seconds):
        self.now = 100000.0 + seconds
        nightly.tick(print)

    def test_the_one_read_after_the_slow_one_waits_out_its_own_hour(self):
        self.tick_at(0)
        slow, later = self.reads
        self.reads.clear()
        self.tick_at(nightly.EVERY - 1)
        self.assertEqual(self.reads, [])
        self.tick_at(nightly.EVERY)
        self.assertEqual(self.reads, [slow])
        self.tick_at(nightly.EVERY + nightly.CEILING - 1)
        self.assertEqual(self.reads, [slow])
        self.tick_at(nightly.EVERY + nightly.CEILING)
        self.assertEqual(self.reads, [slow, later])

    def test_the_one_stamp_of_the_version_before_holds_every_checkouts_hour(self):
        (config.STATE / "nightly.json").write_text(json.dumps({"asked": 100000.0}))
        self.tick_at(nightly.EVERY - 1)
        self.assertEqual(self.reads, [])
        self.tick_at(nightly.EVERY)
        self.assertEqual(sorted(self.reads), ["acme", "zen"])


if __name__ == "__main__":
    unittest.main()
