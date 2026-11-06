"""The tick keeps each provider's usage reading current, asking each at most once a minute.

With no menu open, the tick's usage read is what keeps every reading current: it asks each
configured provider's harness for its meters, except one asked within the last minute, and what
it read is what `ak usage` then shows, with no ask of its own.  A dry tick asks nobody.

The minute is on the program's clock, so the key moves time by dating the last ask where it is
written down, each provider's `state/<provider>-probe.lock` and the snapshot's `fetched_at` in
`state/usage.json`, on its own clock: a few seconds back for the tick within the minute, so a
slow tick before it cannot push it past the minute, and 61 seconds back once it has passed.  It
does so only after seeing that the tick which asked wrote each of them down while it ran: a
program that wrote a wrong moment would ask twice in two ordinary ticks.

Black-box: the program `AK_BIN` names ticks from outside through tests/fixtures/akbin.py, its
two providers on the harness of tests/fixtures/meters.py, which logs every verb it is asked;
this test fails against `/bin/false`.
"""

from collections import Counter
import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import boxable, Home

FIRST = {"acme": 30, "brine": 70}       # each provider's week, used%, as the first tick reads it
LATER = {"acme": 45, "brine": 85}       # ... and once the minute has passed
STATE = ".agentkit/state"
WITHIN = 5      # seconds back the last ask is dated for the tick within the minute
PAST = 61       # ... and for the tick once it has passed


def written(home):
    """When the program wrote down its last ask: each provider's lock, and the snapshot's
    `fetched_at`; None where it wrote none."""
    def read(name, parse):
        try:
            return parse((home.path / STATE / name).read_text())
        except (OSError, ValueError, KeyError, TypeError):
            return None
    return {**{name: read(f"{name}-probe.lock", float) for name in FIRST},
            "usage.json": read("usage.json", lambda text: json.loads(text)["fetched_at"])}


def date(home, ago):
    """Date the last ask `ago` seconds back on the key's clock, wherever `written` reads it."""
    at = time.time() - ago
    for name in FIRST:
        home.write(f"{STATE}/{name}-probe.lock", repr(at))
    snapshot = json.loads((home.path / STATE / "usage.json").read_text())
    home.write(f"{STATE}/usage.json", {**snapshot, "fetched_at": at})


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class TickKeepsUsageCurrent(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.meter = meters.install(self.home)
        self.answer(FIRST)
        akconfig.write(self.home, {"anvil": {"harness": "echo", "provider": "acme"},
                                   "bolt": {"harness": "echo", "provider": "brine"}})

    def answer(self, used):
        for name, percent in used.items():
            self.meter.week(name, used=percent)

    def asked(self, run, *args):
        """What `run(*args)` printed, once it exited 0, and how many times it asked each
        provider for its usage."""
        usage = lambda: Counter(name for verb, name, _ in self.meter.calls() if verb == "usage")
        before = usage()
        done = run(*args)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done, dict(usage() - before)

    def tick_asking_each(self):
        """A tick asks each provider once and writes down, while it runs, that it did."""
        before = time.time()
        _, asks = self.asked(self.home.tick)
        after = time.time()
        self.assertEqual(asks, dict.fromkeys(FIRST, 1))
        moments = written(self.home)
        self.assertEqual([name for name, at in moments.items()
                          if at is None or not before <= at <= after], [],
                         f"written {moments}, the tick ran from {before} to {after}")

    def test_a_tick_asks_each_provider_once_a_minute_and_ak_usage_shows_what_it_read(self):
        self.tick_asking_each()
        date(self.home, WITHIN)
        self.assertEqual(self.asked(self.home.tick)[1], {}, "a tick within the minute asked")
        self.answer(LATER)
        date(self.home, PAST)
        self.assertEqual(self.asked(self.home.ak, "watch", "--dry-run")[1], {},
                         "a dry tick asked")
        self.tick_asking_each()
        done, asks = self.asked(self.home.ak, "usage", "--json")
        self.assertEqual(asks, {}, "`ak usage` asked")
        shown = json.loads(done.out)["providers"]
        self.assertEqual({name: [meter["used"] for meter in shown[name]["meters"]]
                          for name in LATER}, {name: [used] for name, used in LATER.items()})


if __name__ == "__main__":
    unittest.main()
