"""`ak models --json` says what one login of each plan `week_meters` names costs a month (`money`):
{"currency", "month": {provider: {plan: price}}}, in the config's `[money] currency`, "USD" or
"EUR", "USD" where it names none; any other, or a `money` that is no table, is refused as the
config loads, exit 2 and one line.

A plan's price is its provider's `price` in the config where that is one number (no boolean) from
0 to 1,000,000, as written, the owner's own word in what they pay in; else the harness's list
price for that plan before tax in that currency, null where it lists none, as no price is
converted from another currency.  A `price` by login is not read: usage is kept by plan.  Claude's
Pro is $20 or 18 euros, Max 5x $100 or 90 euros, Max 20x $200 or 180 euros; ChatGPT's Pro is $200
and no euro price, the $500 plan a login names `promax` $500 or 429 euros.

Black-box: the program `AK_BIN` names, the `claude` and `codex` harnesses being
tests/fixtures/meters.py's script beside their shipped manifests, each login's readings written
into its Home as tests/test_key_models_json_week_meters.py writes them.  Fails against /bin/false.
"""

from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards
from test_key_models_json_week_meters import DAY, NOW, TABLES, WeekMeters

LOGINS = {"anthropic": ["default", "second"], "openai": ["default", "second"]}
# the plan each login's readings name
PLANS = {("anthropic", "default"): "max 20x", ("anthropic", "second"): "team",
         ("openai", "default"): "pro"}


class ModelsJsonMoney(WeekMeters):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for harness in ("claude", "codex"):
            shutil.copy2(meter.dir / "echo.sh", meter.dir / f"{harness}.sh")
        self.home.write(".agentkit/state/boards.json", boards())
        week = {"name": "weekly", "used": 50, "window_secs": 7 * DAY, "resets_at": NOW + DAY}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": NOW, "providers": {
            provider: {"accounts": {account: {"meters": [week]} for account in accounts}}
            for provider, accounts in LOGINS.items()}})
        self.plans = dict(PLANS)

    def configure(self, money=None, **providers):
        """The config: `money` its `money` where given, and each provider's table given its keys
        in `providers`."""
        akconfig.write(self.home, {"anvil": "claude", "bolt": "codex"},
                       providers={provider: {"mode": "subscription", "accounts": accounts,
                                             **providers.get(provider, {})}
                                  for provider, accounts in LOGINS.items()},
                       settings=None if money is None else {"money": money})

    def money(self, currency=None, **providers):
        """`ak models --json`'s `money`, the config's `[money] currency` `currency` where given and
        each provider's table given its keys in `providers`, each login of `self.plans` having
        risen 10 points on its plan."""
        self.configure(currency and {"currency": currency}, **providers)
        self.rows = {table: [] for table in TABLES}
        for (provider, account), plan in self.plans.items():
            self.read(50, 10, plan, account, provider)
            self.read(40, 20, plan, account, provider)
        (self.home.path / ".agentkit/history.db").unlink(missing_ok=True)
        return self.answer()["money"]

    def test_dollars_where_the_config_names_no_currency(self):
        self.assertEqual(self.money(), {"currency": "USD", "month": {
            "anthropic": {"max 20x": 200, "team": None}, "openai": {"pro": 200}}})

    def test_euros_from_the_euro_table_and_a_plan_it_does_not_hold_has_none(self):
        self.assertEqual(self.money("EUR"), {"currency": "EUR", "month": {
            "anthropic": {"max 20x": 180, "team": None}, "openai": {"pro": None}}})

    def test_a_price_of_one_number_wins_in_either_currency_and_one_by_login_changes_nothing(self):
        for currency, pro in (("USD", 200), ("EUR", None)):
            with self.subTest(currency):
                self.assertEqual(self.money(currency, anthropic={"price": 175.5},
                                            openai={"price": {"default": 100, "second": 100}}),
                                 {"currency": currency, "month": {
                                     "anthropic": {"max 20x": 175.5, "team": 175.5},
                                     "openai": {"pro": pro}}})
        self.assertEqual(self.money("USD", anthropic={"price": 0}, openai={"price": 1_000_000}),
                         {"currency": "USD", "month": {
                             "anthropic": {"max 20x": 0, "team": 0},
                             "openai": {"pro": 1_000_000}}})
        # a boolean, negative, past 1,000,000 or non-number is no price
        for anthropic, openai in ((True, -1), (1_000_001, "200")):
            with self.subTest((anthropic, openai)):
                self.assertEqual(self.money("EUR", anthropic={"price": anthropic},
                                            openai={"price": openai}),
                                 {"currency": "EUR", "month": {
                                     "anthropic": {"max 20x": 180, "team": None},
                                     "openai": {"pro": None}}})

    def test_a_currency_neither_usd_nor_eur_or_no_table_is_refused(self):
        path = self.home.path / ".agentkit/config.toml"
        for money, why in (({"currency": "GBP"}, '[money] currency must be "USD" or "EUR"'),
                           ({"currency": "EUR\n"}, '[money] currency must be "USD" or "EUR"'),
                           ({"currency": ["USD"]}, '[money] currency must be "USD" or "EUR"'),
                           ("EUR", "[money] must be a table"),
                           (10 ** 5000, "[money] must be a table")):
            with self.subTest(why):
                self.configure(money)
                done = self.home.ak("models", "--json", env=ENV)
                self.assertEqual((done.code, done.out, done.err),
                                 (2, "", f"ak models: {path}: {why}\n"))

    def test_the_500_dollar_plan_promax_is_priced_in_both(self):
        self.plans[("openai", "second")] = "promax"
        for currency, price in (("USD", 500), ("EUR", 429)):
            with self.subTest(currency):
                self.assertEqual(self.money(currency)["month"]["openai"]["promax"], price)


if __name__ == "__main__":
    unittest.main()
