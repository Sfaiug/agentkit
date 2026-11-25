"""`Subscriptions` on `c` says a subscription's resets in hand only on the row the highlight is on.

The owner (10 Nov 2026): "also in the main menu it only shows a reset on the main menu, here it
always hsows, make it only show when hovering. I want absolute consistency!!!"  Beside its meter
where there is room, else on the line under it, and on no other row.  Black-box: `AK_BIN`'s menu
in a terminal (tests/fixtures/akterm.py) over two subscriptions in a temporary HOME that each hold
a reset, harnesses faked (tests/fixtures/fakeadapter.py), NO_COLOR.  This test fails against
`/bin/false`.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_subscriptions_page import MAIN_KEYS, PAGE, PAGE_KEYS, UNLIT, body, lines, title


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ResetsInHandOnTheLitRow(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        now = time.time()

        def used(percent, *meters):
            return {"meters": [{"name": "weekly", "used": percent, "window_secs": 604800},
                               *meters], "resets": 1, "error": None, "probed_at": now}
        # Claude's 5-hour window: a limit its lit row's line says, the resets in hand not among
        window = {"name": "session", "used": 25, "window_secs": 18000, "resets_at": int(now + 3600)}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": used(16, window), "openai": used(57)}})
        self.home.write(".agentkit/state/logins.json", {
            "anthropic": {"default": {"email": "owner@acme.test", "plan": "max 20x",
                                      "checked_at": now}},
            "openai": {"default": {"email": "owner@acme.test", "plan": "plus",
                                   "checked_at": now}}})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen) and "Claude" in screen
                       and "ChatGPT" in screen)
        self.term.keys("c")
        self.term.wait(lambda screen: "› Fable 5.1" in screen)
        self.term.keys("Down", "Down", "Down")        # past 6 Astra and `Models`
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.page = self.term.wait(lambda shown: title(shown) == PAGE and "› Claude " in shown
                                   and UNLIT in lines(shown))

    def test_resets_in_hand_show_only_on_the_lit_subscription_s_row(self):
        self.assertEqual(self.page.count("reset in hand"), 1)
        self.assertEqual(body(self.page), [
            "Anthropic",
            "› Claude   ━━━━━━━━╸─  84% left · 1 reset in hand",
            "    5h 75% left",
            "    owner@acme.test · ULTRA   → spend a reset   − remove",
            "OpenAI",
            "  ChatGPT  ━━━━╸─────  43% left",
            "",
            "  + add a subscription"])

        self.term.keys("Down")
        second = self.term.wait(lambda shown: "› ChatGPT " in shown and " · plus " in shown
                                and UNLIT in lines(shown))
        self.assertEqual(second.count("reset in hand"), 1)
        self.assertEqual(body(second), [
            "Anthropic",
            "  Claude   ━━━━━━━━╸─  84% left",
            "OpenAI",
            "› ChatGPT  ━━━━╸─────  43% left · 1 reset in hand",
            "    owner@acme.test · plus   → spend a reset   − remove",
            "",
            "  + add a subscription"])

        self.term.keys("Down")
        add = self.term.wait(lambda shown: "› + add a subscription" in lines(shown)
                             and "− remove" not in shown and PAGE_KEYS.format("open") in lines(shown))
        self.assertEqual(add.count("reset in hand"), 0)
        self.assertEqual(body(add), [
            "Anthropic",
            "  Claude   ━━━━━━━━╸─  84% left",
            "OpenAI",
            "  ChatGPT  ━━━━╸─────  43% left",
            "",
            "› + add a subscription"])

    def test_folded_under_a_narrow_meter_and_moved_with_the_pointer(self):
        row = next(number for number, line in enumerate(lines(self.page), 1)
                   if line.startswith("  ChatGPT "))
        self.term.type(f"\x1b[<35;5;{row}M")
        hovered = self.term.wait(lambda shown: "› ChatGPT " in shown and " · plus " in shown
                                 and UNLIT in lines(shown))
        self.assertEqual(hovered.count("reset in hand"), 1)
        self.assertIn("› ChatGPT  ━━━━╸─────  43% left · 1 reset in hand", body(hovered))

        # onto its row as drawn now, Claude's lines gone from over it: the still pointer may be
        # left on no row's, and a move from nothing onto nothing lets no row go (terminal.lit)
        row = next(number for number, line in enumerate(lines(hovered), 1)
                   if line.startswith("› ChatGPT "))
        self.term.type(f"\x1b[<35;5;{row}M")
        self.term.type("\x1b[<35;5;1M")               # on the header, off every row
        away = self.term.wait(lambda shown: "› " not in shown and "− remove" not in shown
                              and UNLIT in lines(shown))
        self.assertEqual(away.count("reset in hand"), 0)

        self.term.resize(40, 40)                      # no room beside the meter: onto its line
        self.term.keys("Up")
        narrow = self.term.wait(lambda shown: len(lines(shown)[0]) <= 40 and "› Claude " in shown
                                and "− remove" in shown and UNLIT in lines(shown))
        shown = body(narrow)
        claude = next(index for index, line in enumerate(shown) if line.startswith("› Claude "))
        chatgpt = next(index for index, line in enumerate(shown) if line.startswith("  ChatGPT "))
        self.assertNotIn("in hand", shown[claude])
        opened = " ".join(line.strip() for line in shown[claude + 1:chatgpt])
        self.assertEqual(opened.count("1 reset in hand"), 1, shown)
        self.assertNotIn("in hand", " ".join(shown[chatgpt:]))


if __name__ == "__main__":
    unittest.main()
