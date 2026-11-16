"""After an ask of a harness's usage ak waits a cooldown before the next: `usage.PROBE_EVERY`,
or the `[usage] probe_every` the harness's manifest names.  Each shipped manifest's cooldown is
at most a minute, or at most its row here, which says what a shorter one costs; a row only goes
down.  Muse's adapter keeps its own answer for `muse_usage.CACHE_TTL` on top, held the same way.

This holds the cooldowns alone.  When the ask after a cooldown comes is its caller's (the tick,
an open menu), and what else ak reads (pull requests, releases, logins) is not measured here.

The owner, 12 Nov 2026: "Are we checking as often as possible, or not?"  Offline: the manifests
as shipped, Python's and Go's copies.
"""

import sys
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import usage
from agentkit.harness import muse_usage

MINUTE = 60
SLOWER = {  # harness: (its cooldown at most, what a shorter one costs)
    "claude": (900, "Anthropic refuses a login asked more often, for an hour each time"),
    "opencode": (900, "each ask boots OpenCode, six seconds of a CPU"),
}
MUSE_KEEPS = 600    # each ask of Muse's usage is a billed request


class AUsageCooldownOnlyGoesDown(unittest.TestCase):
    def test_the_usual_cooldown_is_at_most_a_minute(self):
        self.assertLessEqual(usage.PROBE_EVERY, MINUTE)

    def test_a_manifest_s_cooldown_is_at_most_a_minute_or_its_row(self):
        manifests = [*(REPO / "adapters").glob("*.toml"),
                     *(REPO / "go/internal/config/adapters").glob("*.toml")]
        self.assertTrue(manifests)
        for manifest in manifests:
            named = tomllib.loads(manifest.read_text()).get("usage", {}).get("probe_every", 0)
            self.assertLessEqual(named, SLOWER.get(manifest.stem, (MINUTE,))[0], str(manifest))

    def test_muse_s_adapter_keeps_an_answer_at_most_ten_minutes(self):
        self.assertLessEqual(muse_usage.CACHE_TTL, MUSE_KEEPS)


if __name__ == "__main__":
    unittest.main()
