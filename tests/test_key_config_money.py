"""`c` shows `Money` last, the currency prices are in after its sign, `$ US dollars` with no
`[money]` in config.toml, and Enter there opens `config · money`: `Currency`, Space on it switching
to `€ euros` and back, each written to `[money] currency` at once.  Without UTF-8 the currency
reads its ISO code for its sign: `USD US dollars`, `EUR euros`.  Under it a row each provider and
plan the logins are on as kept, in the order `config · subscriptions` lists them: its price a
month in that currency and its logins where more than one, else `no price in` it, or `plan not
read yet` by its provider alone; then `In all`, each price times its logins, naming the logins
it did not count.  Claude's Max 20x is $200 or 180 euros, Pro $20; ChatGPT's Plus $20 and no
euro price.

The owner, 24 Nov 2026: "user should be able to choose euro or dollar"; "we want to know how
much is the user paying per month".  Black-box: `AK_BIN`'s
menu in a terminal (tests/fixtures/akterm.py), NO_COLOR, the harnesses fakes of
tests/fixtures/fakeadapter.py.  Fails against `/bin/false`.
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

    def plans(self, plans):
        """`config · money` opened, each login of `plans`, {provider: {account: plan}}, kept on its
        plan, asked just now: listed in that order, and the providers' other logins none."""
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"}, providers={
            provider: {"mode": "subscription", "accounts": list(accounts)}
            for provider, accounts in plans.items()})
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
                            ("Anthropic · max 20x", "$200 a month · 2 logins"),
                            ("Anthropic · pro", "$20 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$440 a month")))

    def test_space_on_currency_prices_them_again_and_in_all_names_a_login_with_no_price(self):
        self.plans({"anthropic": {"default": "max 20x"}, "openai": {"default": "plus"}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("Anthropic · max 20x", "$200 a month"),
                            ("OpenAI · plus", "$20 a month"),
                            ("In all", "$220 a month")))
        self.term.keys("Space")
        self.term.wait(page(("Currency", "€ euros"),
                            ("Anthropic · max 20x", "€180 a month"),
                            ("OpenAI · plus", "no price in euros"),
                            ("In all", "€180 a month · 1 login not counted")))

    def test_a_login_with_no_plan_kept_is_its_provider_alone(self):
        self.plans({"anthropic": {"default": "pro"}, "openai": {"default": None}})
        self.term.wait(page(("Currency", "$ US dollars"),
                            ("Anthropic · pro", "$20 a month"),
                            ("OpenAI", "plan not read yet"),
                            ("In all", "$20 a month · 1 login not counted")))


if __name__ == "__main__":
    unittest.main()
