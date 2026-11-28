"""`c` shows `Money` last, the currency prices are in after its sign, `$ US dollars` with no
`[money]` in config.toml, and Enter there opens `config · money`: `Currency`, Space on it switching
to `€ euros` and back, each written to `[money] currency` at once.  Without UTF-8 the currency
reads its ISO code for its sign: `USD US dollars`, `EUR euros`.  Under it `VAT`, `none` or
`19% · added to list prices`, Enter opening a field for the percent added to each list price,
written to `[money] vat` at once, empty taking it out.  Then a row each provider and plan the
logins were on when the page opened, in the order `config · subscriptions` lists them: its price
a month in that currency (with `your price` where `[money.paid.<currency>.<provider>]` keeps one)
and its logins where more than one, else `no price in` it, or `plan not read yet` by its provider
alone; Enter on a plan's row opens a field for what you pay a month in that currency, written at
once, empty taking it out again, while a row with no plan stays one that only shows; then
`In all`, each price times its logins, naming the logins it did not count.  Claude's Max 20x is
$200 or 180 euros, Pro $20; ChatGPT's Plus $20 and no euro price.

The owner, 24 Nov 2026: "user should be able to choose euro or dollar"; "we want to know how
much is the user paying per month"; "user should be able to choose between net or vat
included".  Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py), NO_COLOR, the
harnesses fakes of tests/fixtures/fakeadapter.py.  Fails against `/bin/false`.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MARK = "  ↑↓←→ move   ␣ mark   esc back"
ASCII = {"LANG": "C", "LC_ALL": ""}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def shows(*patterns):
    """A screen with a line matching each of `patterns`."""
    return lambda screen: all(any(re.fullmatch(pattern, line) for line in lines(screen))
                              for pattern in patterns)


def page(*rows):
    """A screen whose rows from `› Currency` on are `rows`, (label, value) each, and no more."""
    def shown(screen):
        cells = [re.split(r" {2,}", line.strip()) for line in lines(screen)]
        at = next((number for number, row in enumerate(cells) if row[0] == "› Currency"), None)
        return at is not None and cells[at:at + len(rows) + 1] == [
            ["› " + rows[0][0], rows[0][1]], *map(list, rows[1:]), [""]]
    return shown


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ConfigMoney(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})

    def money(self, value, env=(), lit="›"):
        """`c` in a terminal of its own, `env` added, the pointer walked onto its last row once
        that is `Money` reading `value`; the screen."""
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1", **dict(env)})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(f"{lit} Fable 5.1")
        self.term.keys(*["j"] * 30)
        return self.term.wait(shows(rf"{lit} Money +{re.escape(value)}"))

    def currency(self):
        return akconfig.read(self.home).get("money")

    def plans(self, plans, money=None):
        """`config · money` opened, each login of `plans`, {provider: {account: plan}}, kept on its
        plan, asked just now: listed in that order, and the providers' other logins none, with
        `[money]` set to `money` where given."""
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"}, providers={
            provider: {"mode": "subscription", "accounts": list(accounts)}
            for provider, accounts in plans.items()},
            settings=None if money is None else {"money": money})
        self.home.write(".agentkit/state/logins.json", {provider: {
            account: {"email": None, "ends": None, "plan": plan, "checked_at": time.time()}
            for account, plan in accounts.items() if plan} for provider, accounts in plans.items()})
        self.money("$ US dollars")
        self.term.keys("Enter")

    def test_c_shows_money_last_in_dollars_with_no_money_table(self):
        shown = lines(self.money("$ US dollars"))
        at = next(number for number, line in enumerate(shown) if line.startswith("› Money"))
        self.assertTrue(shown[at - 1].startswith("  Limits "), shown)
        self.assertEqual(shown[at + 1], "", shown)          # the build under it: no row after
        self.assertTrue(shown[at + 2].startswith("  Version "), shown)
        self.assertIsNone(self.currency())

    def test_space_on_currency_writes_euros_and_again_dollars(self):
        self.money("$ US dollars")
        self.term.keys("Enter")
        self.term.wait(shows(r"agentkit · config · money +\d\d:\d\d",
                             r"› Currency +\$ US dollars", re.escape(MARK)))
        self.term.keys("Space")
        self.term.wait(shows(r"› Currency +€ euros"))
        self.assertEqual(self.currency(), {"currency": "EUR"})
        self.term.keys("Escape")
        self.term.wait(shows(r"› Money +€ euros"))
        self.term.keys("Enter")
        self.term.wait(shows(r"› Currency +€ euros"))
        self.term.keys("Space")
        self.term.wait(shows(r"› Currency +\$ US dollars"))
        self.assertEqual(self.currency(), {"currency": "USD"})

    def test_an_ascii_terminal_reads_the_codes(self):
        self.money("USD US dollars", ASCII, ">")
        self.term.keys("Enter")
        self.term.wait(shows(r"> Currency +USD US dollars"))
        self.term.keys("Space")
        self.term.wait(shows(r"> Currency +EUR euros"))
        self.term.keys("Escape")
        self.term.wait(shows(r"> Money +EUR euros"))

    def test_each_plan_at_its_price_its_logins_counted_and_in_all_their_sum(self):
        self.plans({"anthropic": {"default": "max 20x", "second": "pro", "third": "max 20x"},
                    "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month · 2 logins"),
                            ("Anthropic · pro", "$20 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$440 a month")))

    def test_space_on_currency_prices_them_again_and_in_all_names_a_login_with_no_price(self):
        self.plans({"anthropic": {"default": "max 20x"}, "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$220 a month")))
        self.term.keys("Space")
        self.term.wait(page(("Currency", "€ euros"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "€180 a month"),
                            ("OpenAI · plus", "no price in euros"),
                            ("In all", "€180 a month · 1 login not counted")))

    def test_a_login_with_no_plan_kept_is_its_provider_alone(self):
        self.plans({"anthropic": {"default": "pro"}, "openai": {"default": None}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · pro", "$20 a month"),
                            ("OpenAI", "plan not read yet"),
                            ("In all", "$20 a month · 1 login not counted")))
        self.term.keys("Down", "Down", "Down")
        shown = self.term.wait(shows(r"› OpenAI +plan not read yet"))
        self.assertNotIn("⏎ open", shown)

    def test_a_kept_price_reads_your_price_and_is_counted_in_all(self):
        self.plans({"anthropic": {"default": "max 20x", "second": "max 20x"},
                    "openai": {"default": "plus"}},
                   money={"paid": {"USD": {"anthropic": {"max 20x": 175.5}}}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$175.50 a month · your price · 2 logins"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$371 a month")))

    def test_a_price_kept_in_euros_leaves_the_dollar_rows_as_they_were(self):
        self.plans({"anthropic": {"default": "max 20x"}, "openai": {"default": "plus"}},
                   money={"paid": {"EUR": {"openai": {"plus": 180}}}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$220 a month")))
        self.term.keys("Space")
        self.term.wait(page(("Currency", "€ euros"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "€180 a month"),
                            ("OpenAI · plus", "€180 a month · your price"),
                            ("In all", "€360 a month")))
        self.term.keys("Space")
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$220 a month")))

    def test_a_price_typed_is_shown_as_your_price_kept_and_counted_in_all(self):
        self.plans({"anthropic": {"default": "max 20x", "second": "max 20x"},
                    "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month · 2 logins"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$420 a month")))
        self.term.keys("Down", "Down", "Enter")
        self.term.wait(shows(r"    a month · empty: the list price", r"  ⏎ save   esc back"))
        self.term.type("175.50")
        self.term.keys("Enter")
        self.term.wait(shows(r"› Anthropic · max 20x +\$175\.50 a month · your price · 2 logins",
                             r"  OpenAI · plus +\$20 a month",
                             r"  In all +\$371 a month"))
        self.assertEqual(self.currency(), {"paid": {"USD": {"anthropic": {"max 20x": 175.5}}}})
        self.term.keys("Up", "Up", "Space")
        self.term.wait(shows(r"› Currency +€ euros", r"  OpenAI · plus +no price in euros"))
        self.term.keys("Down", "Down", "Down", "Enter")
        self.term.wait(shows(r"    a month · empty: the list price", r"  ⏎ save   esc back"))
        self.term.type("180")
        self.term.keys("Enter")
        self.term.wait(shows(r"› OpenAI · plus +€180 a month · your price",
                             r"  In all +€540 a month"))
        self.assertEqual(self.currency(), {
            "currency": "EUR",
            "paid": {"USD": {"anthropic": {"max 20x": 175.5}},
                     "EUR": {"openai": {"plus": 180}}}})

    def test_nothing_typed_puts_the_list_price_back(self):
        self.plans({"anthropic": {"default": "max 20x"}, "openai": {"default": "plus"}},
                   money={"paid": {"USD": {"anthropic": {"max 20x": 180}}}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$180 a month · your price"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$200 a month")))
        self.term.keys("Down", "Down", "Enter")
        self.term.wait("⏎ save")
        self.term.keys("Escape")
        self.term.wait(shows(r"› Anthropic · max 20x +\$180 a month · your price"))
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.keys("Enter")
        self.term.wait(shows(r"› Anthropic · max 20x +\$200 a month",
                             r"  In all +\$220 a month"))
        self.assertIsNone(self.currency())

    def test_a_text_that_is_no_price_writes_nothing_and_says_why(self):
        self.plans({"anthropic": {"default": "max 20x"}, "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$220 a month")))
        config = self.home.path / ".agentkit/config.toml"
        before = config.read_bytes()
        self.term.keys("Down", "Down")
        self.term.wait(shows(r"› Anthropic · max 20x +\$200 a month"))
        for bad in ("abc", " 180", "0", "1.234", "1000001", " ", "18\t0", "\t"):
            with self.subTest(bad=bad):
                self.term.keys("Enter")
                self.term.wait("⏎ save")
                self.term.type(bad)
                self.term.keys("Enter")
                self.term.wait(shows(r"› Anthropic · max 20x +\$200 a month",
                                     r"  a price is a number like 180 or 180\.50"))
                self.assertEqual(config.read_bytes(), before)

    def test_a_vat_typed_is_shown_kept_and_added_to_each_list_price_but_not_your_price(self):
        self.plans({"anthropic": {"default": "max 20x", "second": "max 20x"},
                    "openai": {"default": "plus"}},
                   money={"paid": {"USD": {"openai": {"plus": 18}}}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month · 2 logins"),
                            ("OpenAI · plus", "$18 a month · your price"),
                            ("In all", "$418 a month")))
        self.term.keys("Down", "Enter")
        self.term.wait(shows(r"    percent · empty: none, as for a business",
                             r"  ⏎ save   esc back"))
        self.term.type("8.1")
        self.term.keys("Enter")
        self.term.wait(shows(r"› VAT +8\.1% · added to list prices",
                             r"  Anthropic · max 20x +\$216\.20 a month · 2 logins",
                             r"  OpenAI · plus +\$18 a month · your price",
                             r"  In all +\$450\.40 a month"))
        self.assertEqual(self.currency(), {"paid": {"USD": {"openai": {"plus": 18}}}, "vat": 8.1})

    def test_nothing_typed_takes_the_vat_out(self):
        self.plans({"anthropic": {"default": "max 20x"}, "openai": {"default": "plus"}},
                   money={"vat": 19})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "19% · added to list prices"),
                            ("Anthropic · max 20x", "$238 a month"),
                            ("OpenAI · plus", "$23.80 a month"),
                            ("In all", "$261.80 a month")))
        self.term.keys("Down", "Enter")
        self.term.wait("⏎ save")
        self.term.keys("Escape")
        self.term.wait(shows(r"› VAT +19% · added to list prices"))
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.keys("Enter")
        self.term.wait(shows(r"› VAT +none", r"  Anthropic · max 20x +\$200 a month",
                             r"  OpenAI · plus +\$20 a month", r"  In all +\$220 a month"))
        self.assertIsNone(self.currency())
        # nothing left to take out: no save, which would replace the file (config.save)
        config = self.home.path / ".agentkit/config.toml"
        before = config.stat().st_ino
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.keys("Enter")
        self.term.wait(shows(r"› VAT +none", r"  ↑↓←→ move   ⏎ open   esc back"))
        self.assertEqual(config.stat().st_ino, before)

    def test_a_text_that_is_no_percent_writes_nothing_and_says_why(self):
        self.plans({"anthropic": {"default": "max 20x"}, "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$220 a month")))
        config = self.home.path / ".agentkit/config.toml"
        before = config.read_bytes()
        self.term.keys("Down")
        self.term.wait(shows(r"› VAT +none"))
        for bad in ("abc", "0", "101", "19.555", " 19"):
            with self.subTest(bad=bad):
                self.term.keys("Enter")
                self.term.wait("⏎ save")
                self.term.type(bad)
                self.term.keys("Enter")
                self.term.wait(shows(r"› VAT +none", r"  a VAT is a percent like 19 or 8\.1"))
                self.assertEqual(config.read_bytes(), before)

    def test_a_plan_changed_while_the_field_is_open_leaves_it_under_its_row(self):
        self.plans({"anthropic": {"default": "max 20x", "second": "pro"},
                    "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · max 20x", "$200 a month"),
                            ("Anthropic · pro", "$20 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$240 a month")))
        self.term.keys("Down", "Down", "Enter")
        self.term.wait(shows(r"    a month · empty: the list price", r"  ⏎ save   esc back"))
        # Move the login onto `pro` while the field is open: the row stays and saves for `max 20x`.
        self.home.write(".agentkit/state/logins.json", {
            "anthropic": {
                "default": {"email": None, "ends": None, "plan": "pro", "checked_at": time.time()},
                "second": {"email": None, "ends": None, "plan": "pro", "checked_at": time.time()},
            },
            "openai": {
                "default": {"email": None, "ends": None, "plan": "plus", "checked_at": time.time()},
            },
        })
        self.term.type("175")
        shown = lines(self.term.wait(shows(r"    175")))
        at = next(number for number, line in enumerate(shown)
                  if line.startswith("  Anthropic · max 20x"))
        self.assertEqual(shown[at + 1], "    175", shown)
        self.term.keys("Enter")
        self.term.wait(shows(r"› Anthropic · max 20x +\$175 a month · your price",
                             r"  In all +\$215 a month"))
        self.assertEqual(self.currency(), {"paid": {"USD": {"anthropic": {"max 20x": 175}}}})

    def test_a_plan_named_with_del_takes_a_price_and_the_config_still_loads(self):
        self.plans({"anthropic": {"default": "pro\x7f"}, "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("VAT", "none"),
                            ("Anthropic · pro", "no price in US dollars"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$20 a month · 1 login not counted")))
        self.term.keys("Down", "Down", "Enter")
        self.term.wait("⏎ save")
        self.term.type("42")
        self.term.keys("Enter")
        self.term.wait(shows(r"› Anthropic · pro +\$42 a month · your price",
                             r"  In all +\$62 a month"))
        self.assertIn(r"\u007f", (self.home.path / ".agentkit/config.toml").read_text())
        self.assertEqual(self.currency(), {"paid": {"USD": {"anthropic": {"pro\x7f": 42}}}})
        done = self.home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.err)


if __name__ == "__main__":
    unittest.main()
