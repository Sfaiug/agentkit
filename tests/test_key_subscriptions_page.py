"""`Subscriptions` on `c`, as the owner chose on 26 Oct 2026: each subscription under its
company, drawn as the main screen draws its meter; the row the highlight is on opens one line,
its login's email and plan, then its acts, the first lit, so Enter signs it in again, never
removes; and what `+ add a subscription` adds comes back lit, its line saying whose it is.
Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py) over usage and logins in a
temporary HOME, harnesses faked (tests/fixtures/fakeadapter.py), NO_COLOR, so the lit act is
bracketed.  This test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ choose   n new   c config   esc leave"
PAGE_KEYS = "  ↑↓←→ move   ⏎ choose   esc back"
PAGE, ADD = "agentkit · config · subscriptions", "agentkit · config · add a subscription"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def title(screen):
    return lines(screen)[0].rsplit(" ", 1)[0].strip()


def body(screen):     # the page between its rule and its key line
    shown = lines(screen)
    return "\n".join(shown[2:shown.index(PAGE_KEYS)]).strip("\n").split("\n")


def meters(screen):   # {label: its meter and what it has left}, as the screen draws them
    return dict(re.findall(r"(Claude I+|ChatGPT)\s+([▰▱]+  \d+% left)", screen))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SubscriptionsPage(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        now = time.time()

        def used(percent):
            return {"meters": [{"name": "weekly", "used": percent, "window_secs": 604800}]}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": {"accounts": {"default": used(16), "two": used(71)}},
            "openai": {**used(0), "resets": 1}}})
        def login(email, plan=None):
            return {"email": email, "ends": None, "plan": plan, "checked_at": now}
        self.home.write(".agentkit/state/logins.json", {
            "anthropic": {"default": login("owner@acme.test", "max 20x"),
                          "two": login("two@acme.test")},
            "openai": {"default": login("owner@acme.test", "plus")}})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.main = self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                   and len(meters(screen)) == 3)
        self.term.keys("c")
        self.term.wait(lambda screen: "› Fable 5.1" in screen)
        self.term.keys("Down", "Down", "Down")        # past GPT-6-Astra and `Models`
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.page = self.term.wait(lambda shown: title(shown) == PAGE and PAGE_KEYS in lines(shown))

    def test_each_subscription_sits_under_its_company_with_the_main_screen_s_meter(self):
        self.assertEqual(body(self.page), [
            "Anthropic",
            "› Claude I   ▰▰▰▰▰▰▰▰▱▱  84% left",
            "    owner@acme.test · max 20x   [↻ log in again]   − remove",
            "  Claude II  ▰▰▰▱▱▱▱▱▱▱  29% left",
            "OpenAI",
            "  ChatGPT    ▰▰▰▰▰▰▰▰▰▰  100% left · 1 reset in hand",
            "",
            "  + add a subscription"])
        self.assertEqual(meters(self.page), meters(self.main))

    def test_the_pointed_row_s_line_shows_its_login_and_enter_signs_it_in_again(self):
        self.term.keys("Down")
        pointed = self.term.wait("› Claude II")
        self.assertEqual(body(pointed)[1:5], [
            "  Claude I   ▰▰▰▰▰▰▰▰▱▱  84% left",
            "› Claude II  ▰▰▰▱▱▱▱▱▱▱  29% left",
            "    two@acme.test   [↻ log in again]   − remove",
            "OpenAI"])
        self.term.keys("Down")
        self.assertIn("    owner@acme.test · plus   [↻ log in again]   ↻ spend a reset   − remove",
                      body(self.term.wait("› ChatGPT")))
        self.term.keys("Right")
        self.term.wait("[↻ spend a reset]")
        self.term.keys("Up")
        self.term.wait("    two@acme.test   [↻ log in again]   − remove")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE and "› Claude II" in screen
                       and self.fakes["claude"].calls("login"))
        [call] = self.fakes["claude"].calls("login")
        self.assertEqual((call["argv"], call["env"].get("AGENTKIT_ACCOUNT")), (["again"], "two"))
        self.assertEqual(akconfig.read(self.home)["providers"]["anthropic"]["accounts"],
                         ["default", "two"])

    def test_a_subscription_just_added_comes_back_pointed_at_with_its_login(self):
        self.fakes["claude"].answer("login-end", '{"email": "new@acme.test", "ends": null}')
        self.term.keys("Down", "Down", "Down", "Enter")      # on `+ add a subscription`
        offered = self.term.wait(lambda screen: title(screen) == ADD and "Claude III" in screen)
        rows = [line[2:] for line in lines(offered)[2:] if line[2:]]
        self.term.keys(*["Down"] * rows.index("Claude III"), "Enter")
        added = self.term.wait(lambda screen: title(screen) == PAGE and "› Claude III" in screen)
        self.assertEqual(body(added)[3:], [
            "› Claude III  — no reading yet",
            "    new@acme.test   [↻ log in again]   − remove",
            "OpenAI", "  ChatGPT     ▰▰▰▰▰▰▰▰▰▰  100% left · 1 reset in hand", "",
            "  + add a subscription"])


if __name__ == "__main__":
    unittest.main()
