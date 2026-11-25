"""A mark running low on usage stands behind the others (the owner, 24 Nov 2026: "ideally we never
let usage run out, we dont want exec or revie rounds to abort becuase usage ran out [...] like
when 1% remaining, pick the other, unless the other also 1%").

Two executors are marked, opus and then astra, each on a harness and provider of its own, astra's
week 40% used.  On `ak usage --json`'s `pick_order` over a fixed list of `AK_PICK_DRAW` values:
with opus's week 97% used opus comes second under every draw; with astra's 97% used too, and
with opus's 90% used, each comes first under some draw.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
harnesses the fakes of tests/fixtures/fakeadapter.py whose meters the test sets.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_writer_reviews_only_without_room import meter, staged

MARKED = ["opus", "astra"]
HARNESS = {"opus": "claude", "astra": "codex"}
DRAWS = [f"20261125-10{minute:02d}-acme-retry" for minute in range(12)]


def orders(case, **used):
    """`pick_order` under each draw, each mark's week the % `used` gives, astra's 40 unless
    given."""
    week = {"astra": 40, **used}
    home = staged(case, MARKED, MARKED,
                  {HARNESS[name]: [meter(pct, time.time() + 3 * 86400)]
                   for name, pct in week.items()},
                  workers=MARKED, claude="pass", codex="pass")
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


if __name__ == "__main__":
    unittest.main()
