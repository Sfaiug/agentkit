"""Every service ak is linked to is read as often as that service allows: each has a ceiling,
the most seconds between two reads of it, one above a minute beside what a faster read costs.
A ceiling only goes down, and a harness that names a slower read of its usage without one fails.

A clock in the code is only the soonest a read is made again; the read is made by the first to
look once it has run out. With no screen open that is the tick, every three minutes, so what the
tick reads is held to its clock rounded up to whole ticks (`ticked`); what only a screen, a
command or a landing reads is held to its clock, while one looks.

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

TICK = google_cloud.PASS    # seconds from one tick to the next


def ticked(clock):
    """The seconds between two reads the tick makes: one at its first pass once `clock` ran out."""
    return -(-clock // TICK) * TICK


USAGE = {   # a harness asked about its usage less often than each tick, and what faster costs
    "claude": (900, "Anthropic refuses a login asked more often, for an hour each time; a "
                    "working seat and a spent login are read by their own turns in between"),
    "opencode": (900, "each ask boots OpenCode, six seconds of a CPU"),
}
CLOCKS = [  # (the seconds between two reads, their ceiling, what is read)
    (ticked(usage.PROBE_EVERY), 180, "a harness's usage, where its manifest names no cadence"),
    (ticked(muse_usage.CACHE_TTL), 720, "Muse's usage: every read is a billed request"),
    (ticked(logins.ASK_EVERY), 3600, "a login's plan and end, off local files; at once when "
                                     "made in ak"),
    (ticked(update.ASK_EVERY), 3600, "a harness's latest release, off the network: up to a "
                                     "minute of the tick each"),
    (ticked(nightly.EVERY), 3600, "a project's newest night, by its own command: up to a "
                                  "minute of the tick each"),
    (ticked(retire.EVERY), 3600, "each project's switches, for those two weeks have proven"),
    (ticked(retire.AGAIN), 86400, "... those of a checkout whose plan lines are written"),
    (ticked(watch.TOKEN_POLL_EVERY), 86400, "a worker token's end, a year from its file's date; "
                                            "at once when the file changes"),
    (ticked(google_cloud.FRESH_FOR), 86400, "what Google Cloud offers, while ak has work to "
                                            "rent for: a listing takes a minute"),
    (usage.CACHE_TTL, 300, "the usage a command that asks for no fresh one is shown"),
    (config.CATALOG_TTL, 60, "a login's model list, asked when a screen shows it"),
    (menu.FEATURES_EVERY, 60, "a project's switches, while the menu shows them"),
    (boards.FRESH_FOR, 86400, "a model board, when the models are shown: none moves faster"),
    (deliver.CHECKS_POLL, 10, "a pull request's checks while it lands"),
]

class EveryLinkedServiceIsReadWithinItsCeiling(unittest.TestCase):
    def test_a_harness_s_usage_is_asked_each_tick_or_says_what_faster_costs(self):
        for manifest in sorted((REPO / "adapters").glob("*.toml")):
            every = (config.manifest(manifest.stem).get("usage") or {}).get("probe_every")
            ceiling = USAGE.get(manifest.stem, (ticked(usage.PROBE_EVERY),))[0]
            self.assertLessEqual(ticked(every or usage.PROBE_EVERY), ceiling, manifest.name)

    def test_no_read_is_later_than_its_ceiling(self):
        for apart, ceiling, reads in CLOCKS:
            self.assertLessEqual(apart, ceiling, reads)

    def test_the_tick_runs_every_three_minutes(self):
        self.assertEqual(TICK, 180)
        self.assertIn('cron_line="*/3 * * * * ', (REPO / "install.sh").read_text())


if __name__ == "__main__":
    unittest.main()
