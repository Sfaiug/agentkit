"""A usage-limit reset is spent only by a key or a click on `↻ spend a reset` itself: a meter's
list and a line on `c` → Subscriptions open lit only on `↻ log in again`, and the light stays on
the act it is on, by what it is, nothing lit once that act is gone.  Antigravity's usual login
offers no `log in again` (`[auth] again = false`): holding a reset, its line and its meter's list
open with nothing lit, and Enter spends nothing.  ChatGPT's line, lit on `↻ spend a reset`, loses
it when its reading comes back with none in hand, and Enter then does nothing.  Black-box:
`AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py) over usage and logins in a temporary
HOME, harnesses faked (tests/fixtures/fakeadapter.py), each logging a reset spent, NO_COLOR, so
the lit act is bracketed.  This test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
UNLIT, LIT = "  ↑↓←→ move   esc back", "  ↑↓←→ move   ⏎ {}   esc back"
PAGE = "agentkit · config · subscriptions"
GEMINI = "    gem@acme.test   {}   {}"
CHATGPT = "    owner@acme.test · plus   {}   {}   {}"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ResetSpentOnlyWhereMoved(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, antigravity="pass", codex="pass")
        # Antigravity's adapter spends a reset as Codex's does, so one spent reaches its log
        agy = self.fakes["antigravity"]
        agy.manifest.write_text(agy.manifest.read_text() + "\n[usage]\nreset = true\n")
        agy.answer("reset-status", '{"available": 1}')
        akconfig.write(self.home, {"gemini": {}, "astra": "codex"})
        now = time.time()
        week = {"meters": [{"name": "weekly", "used": 30, "window_secs": 604800}]}
        self.usage = self.home.path / ".agentkit/state/usage.json"
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "google": {**week, "resets": 1}, "openai": {**week, "resets": 1}}})

        def login(email, plan=None):
            return {"default": {"email": email, "ends": None, "plan": plan, "checked_at": now}}
        self.home.write(".agentkit/state/logins.json", {
            "google": login("gem@acme.test"), "openai": login("owner@acme.test", "plus")})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.main = self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                   and "Gemini" in screen and "ChatGPT" in screen)

    def spent(self):
        return [call for fake in self.fakes.values() for call in fake.calls("reset")]

    def subscriptions(self):
        self.term.keys("c")
        self.term.wait("  Subscriptions")
        self.term.keys("Down", "Down", "Down")        # past the two models and `Models`
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        return self.term.wait(lambda screen: PAGE in screen and "› Gemini " in screen)

    def test_a_line_with_no_log_in_again_opens_with_nothing_lit(self):
        self.subscriptions()
        self.term.wait(lambda screen: GEMINI.format("↻ spend a reset", "− remove")
                       in lines(screen) and UNLIT in lines(screen))
        self.term.keys("Enter", "Right")
        self.term.wait(lambda screen: GEMINI.format("[↻ spend a reset]", "− remove")
                       in lines(screen) and LIT.format("spend a reset") in lines(screen))
        self.assertEqual(self.spent(), [])

    def test_a_meter_with_no_log_in_again_opens_its_list_with_nothing_lit(self):
        shown = lines(self.main)
        row = next(number for number, line in enumerate(shown) if "Gemini" in line)
        column = shown[row].index("Gemini") + 3
        self.term.type(f"\x1b[<0;{column};{row + 1}M\x1b[<0;{column};{row + 1}m")
        self.term.wait(lambda screen: "  ↻ spend a reset" in lines(screen)
                       and UNLIT in lines(screen))
        self.term.keys("Enter", "Down")
        self.term.wait(lambda screen: "› ↻ spend a reset" in lines(screen)
                       and LIT.format("spend a reset") in lines(screen))
        self.assertEqual(self.spent(), [])

    def test_the_act_lit_gone_from_under_the_light_leaves_nothing_lit(self):
        self.subscriptions()
        self.term.keys("Down")
        self.term.wait(CHATGPT.format("[↻ log in again]", "↻ spend a reset", "− remove"))
        self.term.keys("Right")
        self.term.wait(lambda screen: CHATGPT.format("↻ log in again", "[↻ spend a reset]",
                                                     "− remove") in lines(screen)
                       and LIT.format("spend a reset") in lines(screen))
        # the menu's opening probe written first, or it writes back the reading it took before
        self.term.wait(lambda _: all("probed_at" in prov for prov in json.loads(
            self.usage.read_text())["providers"].values()))

        def rewritten(screen):    # again until it shows: a write begun before it puts it back
            reading = json.loads(self.usage.read_text())
            if reading["providers"]["openai"].get("resets"):
                reading["providers"]["openai"]["resets"] = 0
                self.home.write(".agentkit/state/usage.json", reading)
            return ("    owner@acme.test · plus   ↻ log in again   − remove" in lines(screen)
                    and UNLIT in lines(screen))
        self.term.wait(rewritten)
        self.term.keys("Enter", "Right")
        self.term.wait(lambda screen: LIT.format("log in again") in lines(screen))
        self.assertEqual((self.spent(), self.fakes["codex"].calls("login")), ([], []))
        self.assertEqual(set(akconfig.read(self.home)["providers"]), {"google", "openai"})


if __name__ == "__main__":
    unittest.main()
