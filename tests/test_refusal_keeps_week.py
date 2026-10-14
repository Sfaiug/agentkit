"""A spent 5-hour window never hides the week.

A Muse refusal -- a refused turn's quota record, or the probe's own 429 -- names only the
window it hit.  The week the last reading held still stands beside it, so the usage row keeps
its bar and says when the 5-hour window opens again, and `ak usage` reads the same week.

Fake adapters in a temporary HOME: the `usage` verb answers out of a file this test writes,
so nothing here reaches a real usage endpoint or a real credential.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, terminal, usage

NOW = 1000000.0
WEEK = 604800
FIVE = 18000

CONFIG = """
[tiers]
A = ["acme"]
B = ["acme"]

[models.acme]
harness = "muse"
model = "m-acme"
effort = "high"
provider = "meta"

[providers.meta]
mode = "subscription"
"""

ADAPTER = """#!/usr/bin/env bash
case "${1:-}" in
usage) cat "$FAKE/usage.json" ;;
*) exit 2 ;;
esac
"""


class RefusalKeepsWeek(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-refusal-week-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = self.root / "fake"
        self.fake.mkdir()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "NO_COLOR": "1", "FAKE": str(self.fake),
            config.ADAPTER_DIR_ENV: str(self.fake)}))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text(CONFIG)
        script = self.fake / "muse.sh"
        script.write_text(ADAPTER)
        script.chmod(0o755)
        (self.fake / "muse.toml").write_text("[usage]\n")
        self.now = [NOW]
        stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: self.now[0]))
        self.cfg = config.load()
        # the last whole reading: the 5-hour window nearly spent, 36% of the week left
        self.five_ends = NOW + 2 * 3600
        self.week_ends = NOW + 4 * 86400
        self.answer([{"name": "window", "used": 99, "resets_at": self.five_ends,
                      "window_secs": FIVE},
                     {"name": "weekly", "used": 64, "resets_at": self.week_ends,
                      "window_secs": WEEK}])
        usage.collect(self.cfg)
        self.now[0] += usage.PROBE_EVERY

    def answer(self, meters):
        (self.fake / "usage.json").write_text(
            json.dumps({"provider": "meta", "meters": meters, "error": None}))

    def spent(self, name):
        return [{"name": name, "used": 100, "resets_at": self.five_ends, "window_secs": FIVE}]

    def row(self):
        return terminal.plain(menu.usage_lines(self.cfg, 120)[1])

    def assert_week_kept(self):
        week = usage.reset_when({"resets_at": self.week_ends}, self.now[0])
        five = usage.reset_when({"resets_at": self.five_ends}, self.now[0]).split()[-1]
        self.assertRegex(self.row(),
                         rf"^\s*Muse\s+\S+\s+36% left · resets {week} · 5h spent until {five}$")
        prov = usage.collect(self.cfg)["meta"]
        self.assertTrue(prov["exhausted"])
        self.assertEqual({m["name"]: m["used"] for m in prov["meters"]}["weekly"], 64)

    def test_a_refused_turn_s_quota_record_keeps_the_week(self):
        # a turn was refused: its plugin wrote the quota record, and the adapter answers it alone
        record = config.STATE / "usage-meta.json"
        record.write_text(json.dumps({"meters": self.spent("quota")}))
        os.utime(record, (self.now[0], self.now[0]))
        self.answer(self.spent("quota"))
        usage.collect(self.cfg, refresh=True)
        self.assert_week_kept()

    def test_the_probe_s_own_429_keeps_the_week(self):
        # no turn was refused; the probe itself was, and the 429 named only the window it hit
        self.answer(self.spent("window"))
        usage.collect(self.cfg, refresh=True)
        self.assert_week_kept()

    def test_a_reading_with_room_is_whole_again(self):
        self.answer(self.spent("window"))
        usage.collect(self.cfg, refresh=True)
        # the window opened again: the reading that says so replaces the refusal's
        self.now[0] = self.five_ends + usage.PROBE_EVERY
        self.answer([{"name": "window", "used": 5, "resets_at": self.five_ends + FIVE,
                      "window_secs": FIVE},
                     {"name": "weekly", "used": 70, "resets_at": self.week_ends,
                      "window_secs": WEEK}])
        usage.collect(self.cfg, refresh=True)
        self.assertRegex(self.row(), r"30% left · resets .* · 5h 95% left$")


if __name__ == "__main__":
    unittest.main()
