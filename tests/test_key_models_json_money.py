"""`ak models --json` says what one login of each plan `week_meters` names costs a month (`money`):
{"currency", "month": {provider: {plan: price}}}, in the config's `[money] currency`, "USD" or
"EUR", "USD" where it names none; `[money] vat`, a number from 0 to 100 (0 where none), is added
to each list price, to the cent, a half cent up.  Any other currency or `vat`, or a `money` that
is no table, is refused as the config loads, exit 2 and one line.

A plan's price is first what config.toml keeps for it in that currency
(`[money.paid.<currency>.<provider>]`), above 0 up to 1,000,000; else its provider's `price` in
the config where that is one number (no boolean) from 0 to 1,000,000, as written, the owner's own
word in what they pay in; else the harness's list price for that plan before tax in that
currency with `[money] vat` percent added, null where it lists none, as no price is converted
from another currency.  A `price` by login is not read: usage is kept by plan.  Claude's Pro is
$20 or 18 euros, Max 5x $100 or 90 euros, Max 20x $200 or 180 euros; ChatGPT's Pro is $200 and no
euro price, the $500 plan a login names `promax` $500 or 429 euros; Google's AI Pro is $19.99.

Black-box: the program `AK_BIN` names, the `claude`, `codex` and `antigravity` harnesses being
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
        for harness in ("claude", "codex", "antigravity"):
            shutil.copy2(meter.dir / "echo.sh", meter.dir / f"{harness}.sh")
        self.home.write(".agentkit/state/boards.json", boards())
        self.logins = dict(LOGINS)
        self.models = {"anvil": "claude", "bolt": "codex"}
        self.plans = dict(PLANS)

    def configure(self, money=None, extra="", **providers):
        """The config: `money` its `money` where given, `extra` TOML appended, and each provider's
        table given its keys in `providers`."""
        week = {"name": "weekly", "used": 50, "window_secs": 7 * DAY, "resets_at": NOW + DAY}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": NOW, "providers": {
            provider: {"accounts": {account: {"meters": [week]} for account in accounts}}
            for provider, accounts in self.logins.items()}})
        akconfig.write(self.home, self.models,
                       providers={provider: {"mode": "subscription", "accounts": accounts,
                                             **providers.get(provider, {})}
                                  for provider, accounts in self.logins.items()},
                       settings=None if money is None else {"money": money}, extra=extra)

    def money(self, currency=None, paid=None, vat=None, extra="", **providers):
        """`ak models --json`'s `money`, the config's `[money] currency` `currency`, `[money.paid]`
        `paid` and `[money] vat` `vat` where given, `extra` TOML appended, and each provider's
        table given its keys in `providers`, each login of `self.plans` having risen 10 points on
        its plan."""
        table = {**({"currency": currency} if currency else {}),
                 **({"paid": paid} if paid is not None else {}),
                 **({"vat": vat} if vat is not None else {})}
        self.configure(table or None, extra=extra, **providers)
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

    def test_a_kept_price_wins_in_its_currency_over_provider_and_list_prices(self):
        paid = {"EUR": {"anthropic": {"max 20x": 150, "team": 25.5}, "openai": {"pro": 190}}}
        self.assertEqual(self.money("EUR", paid=paid, anthropic={"price": 175.5}),
                         {"currency": "EUR", "month": {
                             "anthropic": {"max 20x": 150, "team": 25.5},
                             "openai": {"pro": 190}}})
        self.assertEqual(self.money("USD", paid=paid, anthropic={"price": 175.5}),
                         {"currency": "USD", "month": {
                             "anthropic": {"max 20x": 175.5, "team": 175.5},
                             "openai": {"pro": 200}}})

    def test_a_kept_value_that_is_no_price_leaves_the_list_price(self):
        listed = {"currency": "USD", "month": {
            "anthropic": {"max 20x": 200, "team": None}, "openai": {"pro": 200}}}
        for paid in (
            {"USD": {"anthropic": {"max 20x": "180", "team": 0}, "openai": {"pro": True}}},
            {"USD": {"anthropic": {"max 20x": -1, "team": 1_000_001}, "openai": {"pro": False}}},
            "not-a-table",
        ):
            with self.subTest(paid=paid):
                self.assertEqual(self.money("USD", paid=paid), listed)
        self.assertEqual(
            self.money(extra='[money.paid.USD.anthropic]\n"max 20x" = nan\nteam = inf\n'),
            listed)

    def test_vat_adds_to_each_list_price_to_the_cent(self):
        self.models["crane"] = "antigravity"
        self.logins["google"] = ["default"]
        self.plans[("google", "default")] = "Google AI Pro"
        # 200 at 19 is whole 238, 19.99 at 19 is 23.7881 -> 23.79; 19.99 at 50 is 29.985, half
        # cent up -> 29.99 (banker's rounding would give 29.98)
        self.assertEqual(self.money(vat=19), {"currency": "USD", "month": {
            "anthropic": {"max 20x": 238, "team": None},
            "openai": {"pro": 238},
            "google": {"Google AI Pro": 23.79}}})
        self.assertEqual(self.money("EUR", vat=19), {"currency": "EUR", "month": {
            "anthropic": {"max 20x": 214.2, "team": None},
            "openai": {"pro": None},
            "google": {"Google AI Pro": None}}})
        self.assertEqual(self.money(vat=50)["month"]["google"]["Google AI Pro"], 29.99)
        self.assertEqual(self.money(vat=0)["month"]["google"]["Google AI Pro"], 19.99)
        self.assertEqual(self.money(vat=100)["month"]["anthropic"]["max 20x"], 400)

    def test_vat_leaves_a_kept_price_and_a_providers_own_price_as_written(self):
        self.plans[("anthropic", "second")] = "pro"
        paid = {"USD": {"anthropic": {"max 20x": 150}}, "EUR": {"anthropic": {"max 20x": 150}}}
        self.assertEqual(self.money("USD", paid=paid, vat=19, openai={"price": 175.5}),
                         {"currency": "USD", "month": {
                             "anthropic": {"max 20x": 150, "pro": 23.8},
                             "openai": {"pro": 175.5}}})
        self.assertEqual(self.money("EUR", paid=paid, vat=19, openai={"price": 175.5}),
                         {"currency": "EUR", "month": {
                             "anthropic": {"max 20x": 150, "pro": 21.42},
                             "openai": {"pro": 175.5}}})

    def test_a_vat_not_a_number_from_0_to_100_is_refused(self):
        path = self.home.path / ".agentkit/config.toml"
        why = f"ak models: {path}: [money] vat must be a number from 0 to 100\n"
        for bad in ("19", "19\n", True, False, -1, 101, -0.1, 100.1, [19], 10 ** 5000):
            with self.subTest(vat=bad):
                self.configure({"vat": bad})
                done = self.home.ak("models", "--json", env=ENV)
                self.assertEqual((done.code, done.out, done.err), (2, "", why))
        for literal in ("nan", "inf", "-inf"):
            with self.subTest(vat=literal):
                self.configure(extra=f"[money]\nvat = {literal}\n")
                done = self.home.ak("models", "--json", env=ENV)
                self.assertEqual((done.code, done.out, done.err), (2, "", why))


if __name__ == "__main__":
    unittest.main()
