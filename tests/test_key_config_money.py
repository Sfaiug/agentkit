"""`c` shows `Money` last, the currency prices are in after its sign, `$ US dollars` with no
`[money]` in config.toml, and Enter there opens `config · money`: `Currency`, Space on it switching
to `€ euros` and back, each written to `[money] currency` at once.  Without UTF-8 the currency
reads its ISO code for its sign: `USD US dollars`, `EUR euros`.

The owner, 24 Nov 2026: "user should be able to choose euro or dollar".  Black-box: `AK_BIN`'s
menu in a terminal (tests/fixtures/akterm.py), NO_COLOR, the harnesses fakes of
tests/fixtures/fakeadapter.py.  Fails against `/bin/false`.
"""

import re
import sys
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


if __name__ == "__main__":
    unittest.main()
