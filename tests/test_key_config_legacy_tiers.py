"""A config.toml from before `[defaults]`, which said the same with two tier lists, is written in
today's form the next time ak saves it.

An install's config.toml is never replaced, so one written before `[defaults]` existed still
holds `[tiers]`: lists `A` and `B`, and the `pace_margin` that lived beside them.  The next save,
a seat's creation, drops `[tiers]`, keeps `pace_margin` as a top-level key and records the new
seat's models as `[defaults]`: a save that kept the old table would leave two answers to what
the next seat starts with, and one that lost the margin would put the owner's back to the
shipped one.  Black-box: `ak orch NAME --model --workers` runs from a terminal through
tests/fixtures/akbin.py on a fake harness, and the file is judged by what it parses to.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures import akconfig, fakeadapter

LEGACY = '''\
[models.one]
harness = "claude"
model = "one"
effort = "high"
provider = "anthropic"

[models.two]
harness = "claude"
model = "two"
effort = "high"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"

[audit]
on = false

[tiers]
A = ["one", "two"]
B = ["one", "two"]
pace_margin = 7
'''


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LegacyTiers(unittest.TestCase):
    def test_a_save_drops_the_tiers_keeps_their_margin_and_records_the_new_seat(self):
        with Home() as home:
            fakeadapter.install(home, claude="pass")
            home.write(".agentkit/config.toml", LEGACY)
            done = home.ak("orch", "demo", "--model", "two", "--workers", "one", tty=True)
            self.assertEqual(done.code, 0, done.err)
            saved = akconfig.read(home)
            self.assertNotIn("tiers", saved)
            self.assertEqual(saved.get("pace_margin"), 7)
            self.assertEqual(saved.get("defaults"), {"orchestrator": "two", "workers": ["one"]})


if __name__ == "__main__":
    unittest.main()
