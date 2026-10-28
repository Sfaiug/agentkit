"""A Gemini subscription of its own login offers `↻ log in again` first on `c` → Subscriptions, as
every other does; Antigravity's usual login does not (`[auth] again = false`): agy restores that
one from the desktop keyring.  Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py)
over usage and logins in a temporary HOME, the harness faked (tests/fixtures/fakeadapter.py),
NO_COLOR, so the lit act is bracketed.  This test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

PAGE = "agentkit · config · subscriptions"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class GeminiSignsInAgain(unittest.TestCase):
    def test_a_named_gemini_account_offers_log_in_again_first_and_the_usual_login_does_not(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, antigravity="pass")
        akconfig.write(home, ["gemini"], providers={
            "google": {"mode": "subscription", "accounts": ["default", "two"]}})
        now = time.time()
        used = {"meters": [{"name": "weekly", "used": 30, "window_secs": 604800}]}
        home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "google": {"accounts": {"default": used, "two": used}}}})
        home.write(".agentkit/state/logins.json", {"google": {
            account: {"email": f"{account}@acme.test", "ends": None, "plan": None,
                      "checked_at": now} for account in ("default", "two")}})
        term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait(lambda screen: "c config" in screen and "Gemini II" in screen)
        term.keys("c")
        term.wait("› Gemini")
        term.keys("Down", "Down")          # past `Models`
        term.wait("› Subscriptions")
        term.keys("Enter")
        usual = term.wait(lambda screen: PAGE in screen and "› Gemini I " in screen)
        self.assertIn("    default@acme.test   − remove", lines(usual))
        term.keys("Down")
        named = term.wait(lambda screen: "› Gemini II " in screen)
        self.assertIn("    two@acme.test   [↻ log in again]   − remove", lines(named))
        self.assertIn("  ↑↓←→ move   ⏎ log in again   esc back", lines(named))
        term.keys("Enter")
        term.wait(lambda screen: PAGE in screen and fakes["antigravity"].calls("login"))
        [call] = fakes["antigravity"].calls("login")
        self.assertEqual((call["argv"], call["env"].get("AGENTKIT_ACCOUNT")), (["again"], "two"))


if __name__ == "__main__":
    unittest.main()
