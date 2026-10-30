"""`↻ log in again` is offered only while a subscription's own login is ending or has ended.

The owner (27 Oct 2026): "Why when I press on usage meters, do I get the option to log in again?
I think this feature is redundant. The user should be alerted, like we do right now for claude
code when he should login again, but not have the option to press on it and just freely login."
A login far from its end offers no `log in again`: a click on its meter lists `↻ spend a reset`
alone while it holds one, and with none opens no list, the pointer on it still saying its line
under the grid; its row on `c` → Subscriptions offers `− remove` alone.  A login inside its
warning window says when it ends on that line, and its meter's list and its row both offer
`↻ log in again` first.  Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py)
over usage and logins in a temporary HOME (TZ=UTC), harnesses faked
(tests/fixtures/fakeadapter.py), NO_COLOR, so the lit act is bracketed.  This test fails against
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

DAY = 86400
MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
UNLIT, LIT = "  ↑↓←→ move   esc back", "  ↑↓←→ move   ⏎ {}   esc back"
PAGE = "agentkit · config · subscriptions"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def under_grid(screen):
    """The ak screen's line under the usage grid: what the meter under the pointer says."""
    shown = lines(screen)
    return shown[max(number for number, line in enumerate(shown) if "▰" in line) + 1]


def acts(screen):
    """A meter's list as drawn, the lit act marked `›`."""
    return [line for line in lines(screen) if line[2:3] == "↻"]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LogInAgainOnlyWhenNeeded(unittest.TestCase):
    def open(self, ends):
        """The ak screen over Claude, holding no reset, and ChatGPT, holding one, each login
        ending `ends` seconds from now."""
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        now = time.time()
        week = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}]}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": week, "openai": {**week, "resets": 1}}})
        self.ends = int(now + ends)
        login = {"default": {"email": "owner@acme.test", "ends": self.ends, "plan": None,
                             "checked_at": now}}
        self.home.write(".agentkit/state/logins.json", {"anthropic": login, "openai": login})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.main = lines(self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                                         and "ChatGPT" in screen))

    def at(self, label):
        """The pointer's place on `label`'s meter, its column then its row."""
        row = next(number for number, line in enumerate(self.main) if label in line)
        return self.main[row].index(label) + 3, row + 1

    def click(self, label):
        column, row = self.at(label)
        self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")

    def subscriptions(self, row, keys):
        """`c` → Subscriptions, once Claude's row, lit as it opens, has `row` under it and the
        key line is `keys`."""
        self.term.keys("Escape")
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.term.keys("Down", "Down", "Down")        # past GPT-6-Astra and `Models`
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: PAGE in screen and "› Claude " in screen
                       and keys in lines(screen) and any(map(row, lines(screen))))

    def test_a_login_far_from_its_end_offers_no_log_in_again(self):
        self.open(60 * DAY)
        self.click("Claude")
        # no list: the ak screen stays, its line under the grid the pointer's meter's
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                       and under_grid(screen).startswith("  Claude  "))
        self.click("ChatGPT")
        listed = self.term.wait(lambda screen: UNLIT in lines(screen) and acts(screen))
        self.assertEqual(acts(listed), ["  ↻ spend a reset"])     # lit only by a move
        self.subscriptions("    owner@acme.test   − remove".__eq__, UNLIT)

    def test_a_login_inside_its_warning_window_offers_log_in_again_first(self):
        self.open(2 * DAY)
        at = time.strftime("%a %d %b %H:%M", time.gmtime(self.ends))
        ends = f"login owner@acme.test ends {at} ("        # then how far off, as the day turns
        column, row = self.at("ChatGPT")
        self.term.type(f"\x1b[<35;{column};{row}M")      # the pointer onto its meter
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                       and under_grid(screen).startswith("  ChatGPT  " + ends))
        self.click("ChatGPT")
        listed = self.term.wait(lambda screen: LIT.format("log in again") in lines(screen)
                                and acts(screen))
        self.assertEqual(acts(listed), ["› ↻ log in again", "  ↻ spend a reset"])
        self.subscriptions(lambda line: line.startswith("    " + ends)
                           and line.endswith(")   [↻ log in again]   − remove"),
                           LIT.format("log in again"))


if __name__ == "__main__":
    unittest.main()
