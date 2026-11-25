"""`→ log in again` is offered only while a subscription's own login is ending or has ended.

The owner (27 Oct 2026): "Why when I press on usage meters, do I get the option to log in again?
I think this feature is redundant. The user should be alerted, like we do right now for claude
code when he should login again, but not have the option to press on it and just freely login."
A login far from its end offers no `log in again`: its row on `c` → Subscriptions offers
`→ spend a reset` while it holds one and `− remove`, nothing lit, and with no reset `− remove`
alone.  A login inside its warning window says when it ends on that line, and its row offers
`→ log in again` first, lit.  Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py)
over usage and logins in a temporary HOME (TZ=UTC), harnesses faked
(tests/fixtures/fakeadapter.py), NO_COLOR, so the lit act is bracketed.  This test fails against
`/bin/false`.
"""

import itertools
import re
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
METER = re.compile(r"[━╸─]+  \d+% left")


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def under_grid(screen):
    """The ak screen's line under the usage grid: what the meter under the pointer says."""
    shown = lines(screen)
    return shown[max(number for number, line in enumerate(shown) if METER.search(line)) + 1]


def acts(screen, label):
    """The acts on the lines `label`'s highlighted row opens on Subscriptions, as drawn, the
    lit one bracketed."""
    shown = lines(screen) if PAGE in screen else []
    at = next((number for number, row in enumerate(shown) if row.startswith(f"› {label} ")), -1)
    opened = itertools.takewhile(lambda line: line.startswith("    "), shown[at + 1:] * (at >= 0))
    return [act for line in opened for act in line.strip().split("   ")
            if act.startswith(("→", "[→", "−"))]


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
        week = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}], "error": None}
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

    def subscriptions(self, row, keys):
        """`c` → Subscriptions, once Claude's row, lit as it opens, has `row` under it and the
        key line is `keys`."""
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.term.keys("Down", "Down", "Down")        # past 6 Astra and `Models`
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: PAGE in screen and "› Claude " in screen
                       and keys in lines(screen) and any(map(row, lines(screen))))

    def test_a_login_far_from_its_end_offers_no_log_in_again(self):
        self.open(60 * DAY)
        self.subscriptions("    owner@acme.test   − remove".__eq__, UNLIT)
        self.term.keys("Down")                  # onto ChatGPT's, holding a reset
        self.term.wait(lambda screen: UNLIT in lines(screen)       # the spend lit only by a move
                       and acts(screen, "ChatGPT") == ["→ spend a reset", "− remove"])

    def test_a_login_inside_its_warning_window_offers_log_in_again_first(self):
        self.open(2 * DAY)
        at = time.strftime("%a %d %b %H:%M", time.gmtime(self.ends))
        ends = f"login owner@acme.test ends {at} ("        # then how far off, as the day turns
        column, row = self.at("ChatGPT")
        self.term.type(f"\x1b[<35;{column};{row}M")      # the pointer onto its meter
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen)
                       and under_grid(screen).startswith("  ChatGPT  " + ends))
        self.subscriptions(lambda line: line.startswith("    " + ends)
                           and line.endswith(")   [→ log in again]   − remove"),
                           LIT.format("log in again"))
        self.term.keys("Down")                  # onto ChatGPT's, holding a reset
        self.term.wait(lambda screen: LIT.format("log in again") in lines(screen)
                       and acts(screen, "ChatGPT")
                       == ["[→ log in again]", "→ spend a reset", "− remove"])


if __name__ == "__main__":
    unittest.main()
