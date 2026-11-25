"""A mark running low on usage stands behind the others (the owner, 24 Nov 2026: "ideally we never
let usage run out, we dont want exec or revie rounds to abort becuase usage ran out [...] like
when 1% remaining, pick the other, unless the other also 1%").

Two executors are marked, opus and then astra, each on a provider of its own, astra's week 40%
used.  On `ak usage --json`'s `pick_order` over a fixed list of `AK_PICK_DRAW` values: with
opus's week 97% used opus comes second under every draw; with astra's 97% used too, and with
opus's 90% used, each comes first under some draw.  Where opus's provider lists several logins,
a spare at 97% used does not demote opus while the usual login at 40% used is the one its turn
runs on; with both logins at 97% used, opus comes second under every draw.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on
harnesses that are only their meters (tests/fixtures/meters.py).
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

MARKED = ["opus", "astra"]
MODELS = {"opus": {"harness": "echo", "provider": "acme", "model": "acme-opus-1"},
          "astra": {"harness": "echo", "provider": "dune", "model": "dune-astra-1"}}
DRAWS = [f"20261125-10{minute:02d}-acme-retry" for minute in range(12)]


def orders(case, **used):
    """`pick_order` under each draw, each mark's week the % `used` gives (or `{login: %}` for a
    provider listing several logins), astra's 40 unless given."""
    home = Home()
    case.addCleanup(home.close)
    meter = meters.install(home)
    providers = {}
    for name, reading in {"astra": 40, **used}.items():
        provider = MODELS[name]["provider"]
        if isinstance(reading, dict):
            providers[provider] = {"mode": "subscription", "accounts": list(reading)}
            for account, pct in reading.items():
                meter.week(provider, account, used=pct)
        else:
            meter.week(provider, used=reading)
    akconfig.write(home, MODELS, workers=MARKED, reviewers=MARKED, providers=providers)
    found = []
    for draw in DRAWS:
        done = home.ak("usage", "--json", env={"AK_PICK_DRAW": draw})
        case.assertEqual(done.code, 0, done.out + done.err)
        found.append(json.loads(done.out)["pick_order"])
    return found


class AMarkRunningLowStandsBehind(unittest.TestCase):
    def test_a_mark_97_percent_used_comes_second_under_every_draw(self):
        self.assertEqual({tuple(order) for order in orders(self, opus=97)}, {("astra", "opus")})

    def test_with_both_97_percent_used_each_comes_first_under_some_draw(self):
        self.assertEqual({order[0] for order in orders(self, opus=97, astra=97)}, set(MARKED))

    def test_with_it_90_percent_used_each_comes_first_under_some_draw(self):
        self.assertEqual({order[0] for order in orders(self, opus=90)}, set(MARKED))

    def test_a_healthy_login_on_the_provider_keeps_its_mark_out_of_low(self):
        self.assertEqual({order[0] for order in orders(self, opus={"default": 40, "second": 97})},
                         set(MARKED))
        self.assertEqual({tuple(order) for order in orders(self, opus={"default": 97, "second": 97})},
                         {("astra", "opus")})


if __name__ == "__main__":
    unittest.main()
