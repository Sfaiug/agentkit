"""`ak usage`'s `a month`, in the table and on a narrow card, is what one login of its plan costs
in `[money] currency` as the Money page prices and writes it (tests/test_key_config_money.py):
Claude's Max 20x `€180` in euros, `EUR 180` without UTF-8, and ChatGPT's Plus, which has no euro
price, `-`; a price typed under `[money.paid]` wins over the list price, and `[money] vat` adds to
a list price.

The owner, 24 Nov 2026: "the usage in % should also be translated to euro amount to how much I
am paying for the respected plan".  Black-box, as tests/test_key_usage_says_a_plan_no_role_marks.py
is and on its fixtures.  Fails against /bin/false.
"""

from pathlib import Path
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home
import test_key_usage_says_a_plan_no_role_marks as marks

PLANS = {"anthropic": ("Claude", "max 20x"), "openai": ("ChatGPT", "plus")}


class UsageAMonthIsWhatYouPay(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for harness in ("claude", "codex"):
            shutil.copy2(meter.dir / "echo.sh", meter.dir / f"{harness}.sh")
        for provider in PLANS:
            meter.week(provider, used=50)
        self.home.write(".agentkit/state/logins.json", {provider: {"default": {
            "email": f"default@{provider}.test", "ends": None, "plan": plan,
            "checked_at": time.time()}} for provider, (_, plan) in PLANS.items()})

    def usage(self, money, env=marks.WIDE):
        """`ak usage`'s text under `env`, with `[money]` set to `money`."""
        akconfig.write(self.home, {"anvil": "claude", "bolt": "codex"},
                       providers={name: {"mode": "subscription"} for name in PLANS},
                       settings={"money": money})
        text = self.home.ak("usage", env=env)
        self.assertEqual(text.code, 0, text.out + text.err)
        return text.out

    def months(self, money, env=marks.WIDE):
        """Each row's `a month` on `ak usage`'s table (`usage`)."""
        out = self.usage(money, env)
        return {label: meters.cell(out, label, "a month") for label, _ in PLANS.values()}

    def test_in_euros_a_plan_s_euro_list_price_is_shown_with_its_sign(self):
        euros = {"currency": "EUR"}
        self.assertEqual(self.months(euros), {"Claude": "€180", "ChatGPT": "-"})
        self.assertEqual(self.months(euros, {**marks.WIDE, "LANG": "C", "LC_ALL": ""}),
                         {"Claude": "EUR 180", "ChatGPT": "-"})
        narrow = self.usage(euros, marks.NARROW)
        self.assertEqual((marks.card_month(narrow, "Claude"), marks.card_month(narrow, "ChatGPT")),
                         ("€180", "-"))

    def test_a_price_typed_under_money_paid_wins(self):
        self.assertEqual(self.months({"paid": {"USD": {"anthropic": {"max 20x": 175.5}}}}),
                         {"Claude": "$175.50", "ChatGPT": "$20"})

    def test_a_vat_adds_to_the_list_price(self):
        self.assertEqual(self.months({"vat": 19}), {"Claude": "$238", "ChatGPT": "$23.80"})


if __name__ == "__main__":
    unittest.main()
