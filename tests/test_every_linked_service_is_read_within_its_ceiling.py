"""Every service ak is linked to is read as often as that service allows: each has a ceiling,
the most seconds between two reads of it, one above a minute beside what a faster read costs.
A ceiling only goes down, and a harness that names a slower read of its usage without one fails.

The owner, 12 Nov 2026: "In general, int he whole of ak, all systems should be as close to live
as possible. See through taht this is the case. Are we checking as often as possible, or not?"
Offline: the shipped manifests and each module's own clock.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, deliver, logins, usage
from agentkit.harness import muse_usage

USAGE = {   # a harness asked about its usage less often than each minute, and what faster costs
    "claude": (900, "Anthropic refuses a login asked more often, for an hour each time; a "
                    "working seat and a spent login are read by their own turns in between"),
    "opencode": (900, "each ask boots OpenCode, six seconds of a CPU"),
}
CLOCKS = [  # (the clock, its ceiling in seconds, what it reads)
    (usage.PROBE_EVERY, 60, "a harness's usage, where its manifest names no cadence"),
    (muse_usage.CACHE_TTL, 600, "Muse's usage: every read is a billed request"),
    (usage.CACHE_TTL, 300, "the usage a command that asks for no fresh one is shown"),
    (config.CATALOG_TTL, 60, "a login's model list, asked when a screen shows it"),
    (logins.ASK_EVERY, 3600, "a login's plan and end, off local files; at once when made in ak"),
    (deliver.CHECKS_POLL, 10, "a pull request's checks while it lands"),
]


class EveryLinkedServiceIsReadWithinItsCeiling(unittest.TestCase):
    def test_a_harness_s_usage_is_asked_each_minute_or_says_what_faster_costs(self):
        for manifest in sorted((REPO / "adapters").glob("*.toml")):
            every = (config.manifest(manifest.stem).get("usage") or {}).get("probe_every")
            ceiling = USAGE.get(manifest.stem, (usage.PROBE_EVERY,))[0]
            self.assertLessEqual(every or usage.PROBE_EVERY, ceiling, manifest.name)

    def test_no_clock_is_slower_than_its_ceiling(self):
        for clock, ceiling, reads in CLOCKS:
            self.assertLessEqual(clock, ceiling, reads)

    def test_the_tick_runs_every_three_minutes(self):
        self.assertIn('cron_line="*/3 * * * * ', (REPO / "install.sh").read_text())


if __name__ == "__main__":
    unittest.main()
