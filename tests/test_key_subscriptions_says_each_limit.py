"""`Subscriptions` on `c` says what each limit of the highlighted login has left.

The owner (24 Nov 2026), of the page with a login highlighted: "here I also want to see fabel
limit / 5 hour limit and others".  Under the highlighted row, before its account line, one dim
line reads what the line under its meter on the ak screen reads, less the label, the login's own
note and the resets in hand, which the row and the account line say; it moves with the highlight,
and a login whose reading says nothing more has no such line.  Black-box: `AK_BIN`'s menu in a
terminal (tests/fixtures/akterm.py) over two Claude logins and a ChatGPT one in a temporary HOME,
their harnesses faked (tests/fixtures/fakeadapter.py), whose failed probes leave each reading as
written, NO_COLOR.  This test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_claude_reset_in_the_menu import METER, WEEK, under_grid
from test_key_subscriptions_page import MAIN_KEYS, PAGE, UNLIT, body, lines, title

FIVE_HOURS = 18000


def reading(now, *meters, **also):
    """A reading as a probe writes one, its own `error` none, of these meters."""
    return {"meters": list(meters), "error": None, "probed_at": now, **also}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SubscriptionsSaysEachLimit(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        now = time.time()
        # Claude I: a week that resets, Fable's own cap spent within it, a 5-hour window and a
        # reset in hand; Claude II: a 5-hour window only; ChatGPT: a week that says nothing more
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": {"accounts": {
                "default": reading(
                    now, {"name": "weekly_all", "used": 40, "resets_at": int(now + 86400),
                          "window_secs": WEEK},
                    {"name": "weekly_scoped", "used": 100, "resets_at": int(now + 86400),
                     "window_secs": WEEK, "scope": "Fable"},
                    {"name": "session", "used": 60, "resets_at": int(now + 3600),
                     "window_secs": FIVE_HOURS}, resets=1),
                "two": reading(now, {"name": "weekly", "used": 20, "window_secs": WEEK},
                               {"name": "session", "used": 25, "resets_at": int(now + 3600),
                                "window_secs": FIVE_HOURS})}},
            "openai": reading(now, {"name": "weekly", "used": 57, "window_secs": WEEK})}})
        login = {"email": "owner@acme.test", "ends": None, "plan": None, "checked_at": now}
        self.home.write(".agentkit/state/logins.json", {
            "anthropic": {"default": login, "two": login}, "openai": {"default": login}})
        self.term = Terminal(self.home, size=(120, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.main = lines(self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                         and "ChatGPT" in screen))

    def spot(self):
        """Where Claude I's meter is: its row and a column inside its label, counted from 1."""
        row = next(number for number, line in enumerate(self.main, 1)
                   if "Claude I " in line and METER.search(line))
        return row, self.main[row - 1].index("Claude I ") + 3

    def test_the_lit_login_s_line_says_its_limits_as_its_meter_s_line_does(self):
        row, column = self.spot()
        self.term.type(f"\x1b[<35;{column};{row}M")
        hovered = under_grid(self.term.wait(
            lambda screen: under_grid(screen).startswith("  Claude I  ") and "5h " in screen))
        notes = hovered.removeprefix("  Claude I  ").split(" · ")
        self.assertEqual(notes[0], "owner@acme.test", hovered)
        self.assertIn("1 reset in hand", notes, hovered)
        said = "    " + " · ".join(note for note in notes[1:] if note != "1 reset in hand")
        self.assertTrue(said.startswith("    resets "), hovered)
        self.assertTrue(said.endswith(" · Fable 0% left · 5h 40% left"), hovered)

        self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        page = body(self.term.wait(lambda shown: title(shown) == PAGE and "› Claude I " in shown
                                   and UNLIT in lines(shown)))
        self.assertEqual(page[1:5], [
            "› Claude I   ━━━━━━────  60% left · 1 reset in hand",
            said,
            "    owner@acme.test   → spend a reset   − remove",
            "  Claude II  ━━━━━━━━──  80% left"])

        self.term.keys("Down")
        page = body(self.term.wait(lambda shown: "› Claude II " in shown
                                   and UNLIT in lines(shown)))
        self.assertEqual(page[1:6], [
            "  Claude I   ━━━━━━────  60% left",
            "› Claude II  ━━━━━━━━──  80% left",
            "    5h 75% left",
            "    owner@acme.test   − remove",
            "OpenAI"])

        self.term.keys("Down")
        page = body(self.term.wait(lambda shown: "› ChatGPT " in shown
                                   and UNLIT in lines(shown)))
        self.assertEqual(page[1:], [
            "  Claude I   ━━━━━━────  60% left",
            "  Claude II  ━━━━━━━━──  80% left",
            "OpenAI",
            "› ChatGPT    ━━━━╸─────  43% left",
            "    owner@acme.test   − remove",
            "",
            "  + add a subscription"])


if __name__ == "__main__":
    unittest.main()
