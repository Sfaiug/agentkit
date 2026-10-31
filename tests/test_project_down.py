"""A seat's project whose `alive:` fails for 5 minutes pages the owner once.

The tick's alive pass (`alive.tick`) on a temporary HOME, a clock the test sets, invented
projects whose `alive:` is `false` or `true`, seats the test files under them, and
tests/fixtures/sink.py standing in for the owner's webhook.
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
from agentkit import alive, config, notify
from fixtures.sink import Sink

# down until the test puts `up` in its checkout
DOWN = "test -e up || { echo probing; echo 502 from acme.test; false; }"


class ProjectDown(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.enterContext(patch.object(config, name, self.root / name.lower()))
        config.ensure_dirs()     # as the tick does
        self.enterContext(patch.dict(os.environ, {"AGENTKIT_DISCORD_USER_ID": "42"}))
        self.sink = self.enterContext(Sink(SimpleNamespace(env=os.environ)))
        self.seats = {}

    def project(self, name, check=None, seat=True):
        """A checkout declaring `check` as its `alive:`, a seat filed under it unless not `seat`."""
        repo = self.root / "code" / name
        repo.mkdir(parents=True)
        (repo / "AGENTS.md").write_text(f"---\nalive: {check}\n---\n" if check else "# acme\n")
        for args in (("init", "-q"), ("add", "AGENTS.md"), ("-c", "user.name=acme", "-c",
                     "user.email=acme@example.com", "commit", "-qm", "init"),
                     ("update-ref", config.RULES_REF, "HEAD")):
            subprocess.run(["git", "-C", str(repo), *args], check=True)
        if seat:
            self.seats[f"fix-{name}"] = {"repo": str(repo)}
        return repo

    def tick(self, minute, fetched):
        """One pass at `minute`, the projects `fetched` fetched; what the owner was sent."""
        self.now = 1_000_000 + 60 * minute
        with patch.object(config, "session_records", return_value=self.seats), \
                patch.object(time, "time", lambda: self.now):
            alive.tick(set(fetched))
        return [request.json for request in self.sink.requests if request.method == "POST"]

    def test_down(self):
        repo = self.project("acme", DOWN)
        for minute in (0, 3):
            self.assertEqual(self.tick(minute, [repo]), [])
        card, = self.tick(6, [repo])
        self.assertEqual(card["content"],
                         "🔴 acme is down since <t:1000000:t> · 502 from acme.test <@42>")
        self.assertEqual(card["allowed_mentions"], {"users": ["42"]})
        self.assertEqual(len(self.tick(9, [repo])), 1)

    def test_blip(self):
        repo = self.project("acme", DOWN)
        self.tick(0, [repo])
        self.tick(3, [repo])
        (repo / "up").touch()
        self.assertEqual(self.tick(4, [repo]), [])
        (repo / "up").unlink()
        self.assertEqual(self.tick(8, [repo]), [])     # down again, since 8

    def test_recovered_before_it_was_out(self):
        repo = self.project("acme", DOWN)
        self.sink.script(503)
        for minute in (0, 3):
            self.tick(minute, [repo])
        self.assertEqual(len(self.tick(6, [repo])), 1)     # refused
        (repo / "up").touch()
        self.tick(7, [repo])
        with patch.object(time, "time", return_value=1_000_000 + 60 * 20):
            notify.retry_pending(log=lambda _line: None)    # no retry of its own, past its wait
        self.tick(20, [repo])
        self.assertEqual(len(self.sink.requests), 1)

    def test_a_refused_card_goes_out_after_an_install_with_the_latest_line(self):
        repo = self.project("acme", "cat why; false")
        (repo / "why").write_text("502 from acme.test\n")
        self.sink.script(503)
        for minute in (0, 3, 6):
            self.tick(minute, [repo])
        (repo / "why").write_text("db refused\n")
        (config.STATE / "installed-at").write_text("1")    # each module is newer than the card
        refused, card = self.tick(9, [repo])
        self.assertEqual(card["content"],
                         "🔴 acme is down since <t:1000000:t> · db refused <@42>")

    def test_a_read_is_timed_as_it_starts(self):
        slow, repo = self.project("a-slow", "true"), self.project("acme", DOWN)
        check = alive.watch.health_command
        def slowly(at, *args, **kw):     # a-slow takes five minutes to pass
            passed = check(at, *args, **kw)
            self.now += 300 * (at == str(slow))
            return passed
        with patch.object(alive.watch, "health_command", slowly):
            self.tick(0, [slow, repo])      # acme's first failing read: at 5
        self.assertEqual(self.tick(6, [repo]), [])

    def test_a_pass_whose_fetch_failed_counts_no_read(self):
        repo = self.project("acme", DOWN)
        self.tick(0, [repo])
        self.assertEqual(self.tick(6, []), [])
        self.assertEqual(len(self.tick(7, [repo])), 1)    # down since 0: the read at 6 never was

    def test_nothing_declared_runs_nothing(self):
        repo = self.project("acme")
        with patch.object(alive.watch, "health_command") as ran:
            for minute in (0, 3, 6):
                self.tick(minute, [repo])
        ran.assert_not_called()
        self.assertEqual(self.sink.requests, [])

    def test_no_seat(self):
        healthy = self.project("acme", "true")
        unfiled = self.project("acme-old", DOWN, seat=False)
        for minute in (0, 3, 6):
            self.assertEqual(self.tick(minute, [healthy, unfiled]), [])


if __name__ == "__main__":
    unittest.main()
