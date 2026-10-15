"""Each subscription shows its monthly price beside its measured week, as what a month buys.

`price` on a provider's table is what each of its subscriptions costs a month, in whatever its
owner pays in.  `ak usage`'s `a month` column, after `holds`, says `200 ≈ 0.15 per 1M tokens`:
the price, and what one million tokens cost at it off the tokens the week holds (a month being
365.25/12 days of them), in grouped digits, `5,000,000` and never `5e+06`; the price alone while
the week is unmeasured, `-` without a price.
`--json` carries `price` and `price_per_1m`.  Offline, on tests/test_subscription_capacity.py's
subscriptions and turns.
"""

from contextlib import redirect_stdout
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_subscription_capacity import Turns
from agentkit import config, usage


class SubscriptionValue(Turns):
    def test_the_price_and_what_a_month_of_it_buys_stand_beside_the_week(self):
        self.cfg["providers"]["anthropic"]["price"] = 200
        self.turn("opus", "default", 3_100_000, weekly=41)
        self.turn("opus", "default", 5_000_000, weekly=43)
        self.turn("opus", "default", 1_200_000, weekly=43)
        self.assertEqual(usage.HEADERS[usage.HEADERS.index("holds") + 1], "a month")
        # 310M a week is 1.35G a month: 200 over 1,348 million
        self.assertEqual(self.row("anthropic I")["a month"], "200 ≈ 0.15 per 1M tokens")
        self.assertEqual(self.row("anthropic II")["a month"], "200")    # its week unmeasured
        self.assertEqual(self.row("openai")["a month"], "-")            # no price

    def test_a_price_of_millions_reads_in_its_digits(self):
        self.cfg["providers"]["anthropic"]["price"] = 5_000_000
        self.turn("opus", "default", 3_100_000, weekly=41)
        self.turn("opus", "default", 5_000_000, weekly=43)
        self.turn("opus", "default", 1_200_000, weekly=43)
        self.assertEqual(self.row("anthropic I")["a month"], "5,000,000 ≈ 3,700 per 1M tokens")
        self.assertEqual(self.row("anthropic II")["a month"], "5,000,000")

    def test_usage_json_carries_the_price_and_what_a_million_costs(self):
        self.cfg["providers"]["anthropic"]["price"] = 200
        self.turn("opus", "default", 3_100_000, weekly=41)
        self.turn("opus", "default", 3_100_000, weekly=43)
        out = io.StringIO()
        with patch.object(config, "load", return_value=self.cfg), \
                patch.object(usage, "pick_order", return_value=[]), \
                patch.object(usage, "review_pair", return_value=None), redirect_stdout(out):
            self.assertEqual(usage.main(["--json"]), 0)
        providers = json.loads(out.getvalue())["providers"]
        claude = providers["anthropic"]["accounts"]
        self.assertEqual((claude["default"]["price"], claude["default"]["price_per_1m"]),
                         (200, 0.22))                  # 207M a week, 899M a month
        self.assertEqual((claude["second"]["price"], claude["second"]["price_per_1m"]),
                         (200, None))
        self.assertEqual((providers["openai"]["price"], providers["openai"]["price_per_1m"]),
                         (None, None))


if __name__ == "__main__":
    unittest.main()
