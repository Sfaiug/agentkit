"""Every bar is the line a seat's progress is drawn with, which a terminal draws itself, so it
looks the same in every one: the owner's pick of 10 Nov 2026, over meters that iTerm2, Ghostty
and Ghostty's tmux popup each drew in another shape.  A subscription's meter is that line over
its cells, heavy for what is left with a half cell where the share ends inside one, the rest
thin; an effort's level is that line over a cell for each level its model offers, heavy up to
the one it runs at; without UTF-8 both are the line's own `==------`.  Black-box: `AK_BIN`'s
menu in a terminal (tests/fixtures/akterm.py) over two Claude subscriptions' usage in a
temporary HOME, harnesses faked (tests/fixtures/fakeadapter.py), NO_COLOR.  This test fails
against `/bin/false`.
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

TWENTY = r"Claude I +{}  20% left"        # the first subscription's meter, 20 of 100 left
SEVENTY_FIVE = r"Claude II +━━━━━━━╸──  75% left"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ABarIsTheLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "max"},
                                   "opus": {"harness": "claude", "effort": "xhigh"}},
                       providers={"anthropic": {"mode": "subscription",
                                                "accounts": ["default", "two"]}})

        def used(percent):
            return {"meters": [{"name": "weekly", "used": percent, "window_secs": 604800}]}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            "anthropic": {"accounts": {"default": used(80), "two": used(25)}}}})

    def menu(self, env):
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1", **env})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        return term

    def test_a_meter_and_an_effort_are_the_line(self):
        term = self.menu({})
        main = term.wait(lambda screen: re.search(TWENTY.format("━━────────"), screen)
                         and re.search(SEVENTY_FIVE, screen))
        term.keys("c")
        config = term.wait(lambda screen: re.search(r"Opus 5\.5 .* ━━━━─ +xhigh", screen)
                           and re.search(r"Fable 5\.1 .* ━━━━━ +max", screen))
        for screen in (main, config):
            self.assertNotRegex(screen, "[▰▱]")

    def test_without_utf8_the_meter_is_the_line_s_own(self):
        self.menu({"LANG": "C", "LC_ALL": ""}).wait(
            lambda screen: re.search(TWENTY.format("==--------"), screen))


if __name__ == "__main__":
    unittest.main()
