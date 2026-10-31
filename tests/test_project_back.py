"""Once its down card is out, a seat's project that passes again sends one card, mentioning
nobody, saying since when it is back and after how long.

The tick's alive pass (`alive.tick`) on a temporary HOME, a clock the test sets, an invented
project whose `alive:` runs the `false` or `true` the test writes in its checkout, a seat filed
under it, and tests/fixtures/sink.py standing in for the owner's webhook.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import alive, config
from fixtures.sink import Sink

BACK = "acme is back since <t:1002700:t>, after 45 min"     # 1_000_000 + 45 min


class ProjectBack(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.enterContext(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()     # as the tick does
        self.enterContext(patch.dict(os.environ, {"AGENTKIT_DISCORD_USER_ID": "42"}))
        self.sink = self.enterContext(Sink(SimpleNamespace(env=os.environ)))
        self.repo = self.root / "code" / "acme"
        self.repo.mkdir(parents=True)
        (self.repo / "AGENTS.md").write_text("---\nalive: sh verdict\n---\n")
        for args in (("init", "-q"), ("add", "AGENTS.md"), ("-c", "user.name=acme", "-c",
                     "user.email=acme@example.com", "commit", "-qm", "init"),
                     ("update-ref", config.RULES_REF, "HEAD")):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)

    def read(self, minute, verdict):
        """One pass at `minute`, acme's check `false` or `true`; the cards this pass sent."""
        (self.repo / "verdict").write_text(verdict)
        before, seats = len(self.sink.requests), {"fix-acme": {"repo": str(self.repo)}}
        with patch.object(config, "session_records", return_value=seats), \
                patch.object(time, "time", lambda: 1_000_000 + 60 * minute):
            alive.tick({self.repo})
        return [request.json for request in self.sink.requests[before:]
                if request.method == "POST"]

    def told(self):
        for minute in (0, 3):
            self.assertEqual(self.read(minute, "false"), [])
        down, = self.read(6, "false")
        self.assertIn("<@42>", down["content"])

    def test_back(self):
        self.told()
        back, = self.read(45, "true")
        self.assertEqual(back["content"], BACK)
        self.assertEqual(back["allowed_mentions"], {"parse": []})
        for minute in (48, 60):
            self.assertEqual(self.read(minute, "true"), [])

    def test_refused_then_out(self):
        self.told()
        self.sink.script(503)
        refused, = self.read(45, "true")
        (config.STATE / "installed-at").write_text("1")    # each module is newer than the card
        back, = self.read(48, "true")
        self.assertEqual([refused["content"], back["content"]], [BACK, BACK])
        self.assertEqual(self.read(51, "true"), [])

    def test_down_again_first(self):
        self.told()
        self.sink.script(503)
        self.read(45, "true")      # refused
        for minute in (48, 51):
            self.assertEqual(self.read(minute, "false"), [])
        down, = self.read(54, "false")     # a new outage, down since 48
        self.assertIn("acme is down since <t:1002880:t>", down["content"])
        back, = self.read(60, "true")
        self.assertEqual(back["content"], "acme is back since <t:1003600:t>, after 12 min")

    def test_never_told(self):
        for minute in (0, 3):
            self.read(minute, "false")
        for minute in (4, 10):
            self.assertEqual(self.read(minute, "true"), [])
        self.assertEqual(self.sink.requests, [])

    def test_durations(self):
        self.assertEqual([alive.lasted(60 * minutes) for minutes in (45, 125, 4320)],
                         ["45 min", "2 h 5 min", "3 days"])


if __name__ == "__main__":
    unittest.main()
