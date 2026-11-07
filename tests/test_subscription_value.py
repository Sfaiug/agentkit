"""Each subscription shows its monthly price beside its week.

`price` on a provider's table is what each of its subscriptions costs a month, in whatever its
owner pays in.  `ak usage`'s `a month` column, after `holds`, says it in grouped digits,
`5,000,000` and never `5e+06`; `-` without a price.  `--json` carries it as `price`.  Offline,
on invented readings in a temporary HOME.
"""

from contextlib import redirect_stdout
import io
import json
import time
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, usage


class SubscriptionValue(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(usage, "_probe",
                                              side_effect=AssertionError("probe")))
        now = time.time()
        week = usage._normalized({"name": "weekly", "used": 40, "resets_at": now + 86400,
                                  "window_secs": 604800}, now)
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": now, "providers": {
            provider: {"provider": provider, "meters": [week], "error": None, "resets": 0.0,
                       "probed_at": now} for provider in ("anthropic", "openai")}}))

    def month(self, provider):
        return next(row for row in usage.rows(self.cfg, usage.collect(self.cfg))
                    if row[0] == provider)[usage.HEADERS.index("a month")]

    def test_the_price_stands_after_the_week_in_its_digits(self):
        self.assertEqual(usage.HEADERS[usage.HEADERS.index("holds") + 1], "a month")
        for price, shown in ((200, "200"), (5_000_000, "5,000,000"), (0.000012, "0.000012")):
            self.cfg["providers"]["anthropic"]["price"] = price
            self.assertEqual(self.month("anthropic"), shown)
        self.assertEqual(self.month("openai"), "-")

    def test_usage_json_carries_the_price(self):
        self.cfg["providers"]["anthropic"]["price"] = 200
        out = io.StringIO()
        with patch.object(config, "load", return_value=self.cfg), \
                patch.object(usage, "pick_order", return_value=[]), \
                patch.object(usage, "review_pair", return_value=None), redirect_stdout(out):
            self.assertEqual(usage.main(["--json"]), 0)
        providers = json.loads(out.getvalue())["providers"]
        self.assertEqual((providers["anthropic"]["price"], providers["openai"]["price"]),
                         (200, None))


if __name__ == "__main__":
    unittest.main()
