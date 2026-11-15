"""Every clock that makes a reader of a service ak is linked to wait has a ceiling: the most
seconds after one read that clock keeps the next from it, one above a minute beside what a faster
read costs. A ceiling only goes down, and a harness that names a slower clock for its usage
without one fails.

Only the clock is held, not how far apart two reads fall. The read after it waits for whoever
looks next, however late: the tick, whose cron line install.sh writes for every three minutes, or
a screen, a command or a landing. And a reader skips a read for reasons that are no clock, as
Muse's does while meters recorded for it have not reset. No test here holds either.

The owner, 12 Nov 2026: "In general, int he whole of ak, all systems should be as close to live
as possible. See through taht this is the case. Are we checking as often as possible, or not?"
Offline: the shipped manifests and each module's own clock.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import (boards, config, deliver, google_cloud, logins, menu, nightly, retire, update,
                      usage, watch)
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
    (menu.FEATURES_EVERY, 60, "a project's switches, while the menu shows them"),
    (deliver.CHECKS_POLL, 10, "a pull request's checks while it lands"),
    (logins.ASK_EVERY, 3600, "a login's plan and end, off local files; at once when made in ak"),
    (update.ASK_EVERY, 3600, "a harness's latest release, off the network: up to a minute of "
                             "the tick each"),
    (nightly.EVERY, 3600, "a project's newest night, by its own command: up to a minute of the "
                          "tick each"),
    (retire.EVERY, 3600, "each project's switches, for those two weeks have proven"),
    (retire.AGAIN, 86400, "... those of a checkout whose plan lines are written"),
    (watch.TOKEN_POLL_EVERY, 86400, "a worker token's end, a year from its file's date; at once "
                                    "when the file changes"),
    (google_cloud.FRESH_FOR, 86400, "what Google Cloud offers, while ak has work to rent for: a "
                                    "listing takes a minute"),
    (boards.FRESH_FOR, 86400, "a model board, when the models are shown: none moves faster"),
]


class EveryClockOnALinkedServiceSReadHasACeiling(unittest.TestCase):
    def test_a_harness_s_usage_clock_is_a_minute_or_says_what_faster_costs(self):
        for manifest in sorted((REPO / "adapters").glob("*.toml")):
            every = (config.manifest(manifest.stem).get("usage") or {}).get("probe_every")
            ceiling = USAGE.get(manifest.stem, (usage.PROBE_EVERY,))[0]
            self.assertLessEqual(every or usage.PROBE_EVERY, ceiling, manifest.name)

    def test_no_clock_is_slower_than_its_ceiling(self):
        for clock, ceiling, reads in CLOCKS:
            self.assertLessEqual(clock, ceiling, reads)

    def test_install_writes_the_tick_s_cron_line_for_every_three_minutes(self):
        self.assertIn('cron_line="*/3 * * * * ', (REPO / "install.sh").read_text())


if __name__ == "__main__":
    unittest.main()
