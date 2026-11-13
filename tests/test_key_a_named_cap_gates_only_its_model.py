"""A cap its provider names for one model gates that model alone.

The owner (11 Nov 2026) saw a Claude login shown empty while its own page read `This week 82%
used` and `Fable 100% used`: Fable's full cap stopped Opus too.  Anthropic's usage endpoint says
whose cap a limit is, `adapters/claude.sh usage` keeps that name as the meter's `scope`, and
the pick reads it: a scoped meter gates only a model whose id or name holds each of its words,
with no model in config.toml claiming the meter.  A meter naming no scope gates every model.

Black-box: the program `AK_BIN` names runs `ak usage --json` from outside through
tests/fixtures/akbin.py, its Claude adapter over a fake `curl` answering the endpoint's shared
week and a second weekly limit as on 11 Nov 2026, both resetting in three days.
This test fails against `/bin/false`.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-2"
FABLE_ONLY = {"model": {"id": None, "display_name": "Fable"}, "surface": None}


def pick_order(case, week, cap, scope=FABLE_ONLY):
    """`ak usage --json`'s pick order over one Claude login whose shared week reads `week`% used
    beside a second weekly limit at `cap`% in `scope`, two workers naming no `meter`."""
    made = Home()
    case.addCleanup(made.close)
    akconfig.write(made, {OPUS: "claude", FABLE: "claude"})
    assert not any("meter" in entry for entry in akconfig.read(made)["models"].values())
    resets = time.strftime("%Y-%m-%dT%H:%M:%S.667575+00:00", time.gmtime(time.time() + 3 * 86400))
    limits = [{"kind": "weekly_all", "group": "weekly", "percent": week, "severity": "warning",
               "resets_at": resets, "scope": None, "is_active": False},
              {"kind": "weekly_scoped", "group": "weekly", "percent": cap, "severity": "critical",
               "resets_at": resets, "scope": scope, "is_active": True}]
    made.write(".agentkit/secrets/claude_oauth_token", "tok-acme")
    answer = made.write("answer.json", {"limits": limits})
    made.fake("curl", f"#!/bin/sh\ncat '{answer}'\nprintf '\\n200'\n")
    made.fake("security", "#!/bin/sh\nexit 1\n")     # no Keychain login on any host
    done = made.ak("usage", "--json")
    case.assertEqual(done.code, 0, done.out + done.err)
    return sorted(json.loads(done.out)["pick_order"])


class NamedCap(unittest.TestCase):
    def test_a_full_fable_cap_leaves_opus_the_shared_week(self):
        self.assertEqual(pick_order(self, 82, 100), [OPUS])

    def test_a_full_shared_week_stops_both(self):
        self.assertEqual(pick_order(self, 100, 10), [])

    def test_room_in_both_picks_both(self):
        self.assertEqual(pick_order(self, 40, 10), sorted([OPUS, FABLE]))

    def test_a_full_cap_naming_no_scope_stops_both(self):
        self.assertEqual(pick_order(self, 82, 100, scope=None), [])


if __name__ == "__main__":
    unittest.main()
