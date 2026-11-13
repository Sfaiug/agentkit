"""Under OpenCode, a provider not logged in to says what a login to it takes: `sign in` where
OpenCode offers an account's sign-in for it, `API key` where it takes only a key; and picking one
that signs in starts OpenCode's first such sign-in for it, not the key prompt.

The owner, 12 Nov 2026: "for opencode I just wanted to add my google AI sub, but it does not let
me, when I pick opencode it wants my gemini API key, this is not right."  OpenCode 2.2.7 lists
each provider's ways in (`opencode api integration.list`, its `methods`): `oauth`, an account's
sign-in, and `external`, one held elsewhere, beside `key` and `env`.  Black-box: the program
`AK_BIN` names, its menu in a person's terminal (tests/fixtures/akterm.py), OpenCode's real
adapter over the Home's fake `opencode`, which lists Acme Cloud, taking a key, an account's
sign-in or another tool's, and Zeta Cloud, taking a key or one in its environment, with no
login to either, and logs each call.  Judged by what the terminal shows under `+ add a
subscription` and the fake's calls; this test fails against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_new_subscription_signs_in_afresh import ADD, MAIN_KEYS, PAGE, lines, row_at, title

INTEGRATIONS = {"data": [
    {"id": "acme", "name": "Acme Cloud", "methods": [
        {"type": "key", "label": "API key"},
        {"id": "acme-account", "type": "oauth", "label": "Sign in with Acme"},
        {"id": "acme-cli", "type": "external", "label": "Acme CLI"}]},
    {"id": "zeta", "name": "Zeta Cloud", "methods": [
        {"type": "key"}, {"type": "env", "names": ["ZETA_API_KEY"]}]}]}
# OpenCode with no login, its lists as 2.2.7 answers them; each call one line of its arguments
OPENCODE = """#!/bin/sh
echo "$*" >> %s
case "$*" in
  "api integration.list") echo '%s' ;;
  "api provider.list"|"api model.list") echo '{"data": []}' ;;
  "api config.get"|"api --standalone config.get") echo '[]' ;;
  "auth list"*) echo '[]' ;;
  "auth login"*) ;;
  *) exit 1 ;;
esac
"""


def offered(screen):
    """The choices OpenCode's list draws, each one's columns."""
    return [re.split(r"\s{2,}", line[4:]) for line in lines(screen)[2:]
            if re.match(r"[ ›]   \S", line)]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpenCodeProviderSaysHowItSignsIn(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.calls = self.home.root / "opencode-calls"
        self.home.fake("opencode", OPENCODE % (self.calls, json.dumps(INTEGRATIONS)))
        akconfig.write(self.home, {"fable": "claude"})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.to("Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE
                       and row_at(screen, "+ add a subscription") is not None)
        self.to("+ add a subscription")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == ADD
                       and row_at(screen, "OpenCode") is not None)
        self.to("OpenCode")
        self.term.keys("Enter")

    def to(self, row):
        """The highlight moved, a line at a time, onto the line that reads `row`."""
        for _ in range(20):
            screen = self.term.wait(lambda screen: row_at(screen, row) is not None and sum(
                line.startswith("› ") for line in lines(screen)) == 1)
            if row_at(screen, row, "›") is not None:
                return
            shown = lines(screen)
            now = next(n for n, line in enumerate(shown) if line.startswith("› "))
            self.term.keys("Down" if row_at(screen, row) > now else "Up")
            self.term.wait(lambda screen: lines(screen)[now] != shown[now])
        self.fail(f"the highlight never reached {row}")

    def logins(self):
        """The arguments of each `opencode auth login` the menu ran."""
        said = self.calls.read_text().splitlines() if self.calls.exists() else []
        return [call.split()[2:] for call in said if call.startswith("auth login")]

    def test_a_provider_says_sign_in_or_api_key_and_a_sign_in_starts_its_first(self):
        shown = self.term.wait(lambda screen: len(offered(screen)) == 2)
        self.assertEqual(offered(shown), [["Acme Cloud", "acme", "sign in"],
                                          ["Zeta Cloud", "zeta", "API key"]])
        self.assertTrue(any(line.startswith("›   Acme Cloud") for line in lines(shown)), shown)
        self.term.keys("Enter")
        self.term.wait(lambda _: self.logins())
        [login] = self.logins()
        self.assertIn("acme", login)
        self.assertEqual(login[login.index("--method") + 1], "acme-account")


if __name__ == "__main__":
    unittest.main()
