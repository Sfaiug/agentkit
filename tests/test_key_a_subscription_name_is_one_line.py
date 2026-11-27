"""A provider's own `name` is one line wherever ak names it: one holding a line break (a hand-edited
`"Acme\\nCloud"`) heads its subscriptions on `Subscriptions` as `Acme Cloud`, one row, so the rows
under it stay where the page put them.  Black-box: `AK_BIN`'s menu in a terminal
(tests/fixtures/akterm.py) in a temporary HOME, its harness faked (tests/fixtures/fakeadapter.py),
NO_COLOR.  This test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_subscriptions_page import MAIN_KEYS, PAGE, body, lines, title


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SubscriptionNameIsOneLine(unittest.TestCase):
    def test_a_name_with_a_line_break_heads_its_subscription_on_one_row(self):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, codex="pass")
        akconfig.write(home, {"anvil": {"harness": "codex", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription", "name": "Acme\nCloud"}})
        term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait(lambda screen: MAIN_KEYS in lines(screen))
        term.keys("c")
        term.wait("› Anvil")
        term.keys("Down", "Down")                     # past `Models`
        term.wait("› Subscriptions")
        term.keys("Enter")
        page = term.wait(lambda shown: title(shown) == PAGE and "+ add a subscription" in shown)
        shown = body(page)
        self.assertEqual(shown[0], "Acme Cloud", shown)
        self.assertTrue(shown[1].startswith("› Acme Cloud "), shown)


if __name__ == "__main__":
    unittest.main()
