"""A state, a choice and an act are marked with characters every terminal font carries.

The owner (10 Nov 2026): "in any terminal, on any operating system, ak should always look the
same."  A character no terminal font carries is borrowed from another font, at another size and
width in each terminal, so a seat out of usage reads `○ out of usage`, told from `○ idle` by its
colour and its words, and under the pointer offers nothing (12 Nov 2026); a meter's acts read
`→ log in again`; a draft `¶ unsent`; the yes-or-no card `✓ Keep` and `× Stop`; `ak run status`
under a run its review failed `× FAIL`; and none of those holds `◌`, `✗`, `↻`, `⇄` or `✎`.
Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py) over seats of
tests/fixtures/akseat.py and usage, logins and runs written under HOME, harnesses faked
(tests/fixtures/fakeadapter.py), NO_COLOR.  This test fails against `/bin/false`.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

GONE = "◌✗↻⇄✎"     # the marks most terminal fonts do not carry
MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
POPUP_KEYS = "  ↑↓←→ move   ⏎ open   n new   x stop   c config   esc leave"
NOW = time.time()
BACK = r"(\w{3} )?\d\d:\d\d"     # when it comes back, its day where that is not today


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MarksEveryFontCarries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Claude spent and ChatGPT with room, its login ending in two days; `acme-draft` holding
        the owner's draft, and `acme-spent` on Claude waiting for its usage."""
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, {"fable": "claude", "astra": "codex"})
        week = {"name": "weekly", "window_secs": 604800}
        home.write(".agentkit/state/usage.json", {
            "fetched_at": NOW, "reset_checked_at": NOW, "providers": {
                "anthropic": {"meters": [{**week, "used": 100, "exhausted": True}]},
                "openai": {"meters": [{**week, "used": 40}], "resets": 1}}})
        login = {"default": {"email": "owner@acme.test", "ends": int(NOW + 2 * 86400),
                             "plan": None, "checked_at": NOW}}
        home.write(".agentkit/state/logins.json", {"anthropic": login, "openai": login})
        Seat(home, "acme-draft", model="fable", screen="claude-draft-pane.txt",
             record={"created": int(NOW) - 900})
        Seat(home, "acme-spent", model="fable", record={"created": int(NOW) - 600})
        home.write(".agentkit/state/seat-acme-spent.json", {"usage_wait": {
            "reason": "anthropic out of usage until 23:00", "until": NOW + 3600,
            "since": NOW - 60, "continue": True}})

    def terminal(self, *args, **env):
        term = Terminal(self.home, *args, size=(100, 40), env={"NO_COLOR": "1", **env})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        return term

    def none_gone(self, screen):
        self.assertEqual([mark for mark in GONE if mark in screen], [], screen)

    def test_a_seat_out_of_usage_offers_nothing_and_a_draft(self):
        term = self.terminal()
        term.wait(lambda screen: MAIN_KEYS in lines(screen))
        term.keys("Down")       # the highlight on acme-spent opens its line, and nothing under it
        opened = rf"\n› \d  acme-spent .*  back {BACK}\n +\S.* ⚒◎\n\n"
        screen = term.wait(lambda screen: re.search(opened, "\n".join(lines(screen)))
                           and "¶ unsent" in screen)
        rows = {found[1]: line for line in lines(screen)
                if (found := re.match(r"[ ›] \d  (\S+)", line))}
        self.assertRegex(rows["acme-spent"], rf"  ○ out of usage  back {BACK}$")
        self.assertRegex(rows["acme-draft"], r"  ○ idle +¶ unsent$")
        self.none_gone(screen)

    def test_a_meter_opened_offers_log_in_again(self):
        term = self.terminal()
        main = lines(term.wait(lambda screen: MAIN_KEYS in lines(screen) and "ChatGPT" in screen))
        row = next(number for number, line in enumerate(main) if "ChatGPT" in line)
        column = main[row].index("ChatGPT") + 3
        term.type(f"\x1b[<0;{column};{row + 1}M\x1b[<0;{column};{row + 1}m")
        screen = term.wait(lambda screen: "› → log in again" in lines(screen))
        self.assertIn("  → spend a reset", lines(screen))
        self.none_gone(screen)

    def test_the_card_before_a_seat_is_stopped(self):
        term = self.terminal("attach", "--overlay", AGENTKIT_SESSION="acme-draft")
        term.wait(lambda screen: POPUP_KEYS in lines(screen))
        term.keys("x")
        screen = term.wait(lambda screen: "  × Stop" in lines(screen))
        self.assertIn("› ✓ Keep", lines(screen))
        self.none_gone(screen)
        term.keys("Escape")     # kept: the other cases' seat stays
        term.wait(lambda screen: POPUP_KEYS in lines(screen))


class FailedRun(unittest.TestCase):
    def test_ak_run_status_over_a_failed_run(self):
        with Home() as home:
            run_id = "20261020-0900-fix-api"
            home.write(f".agentkit/runs/{run_id}/run.json", {
                "run_id": run_id, "title": "fix-api", "executor": "opus", "reviewer": "astra",
                "rounds": 3, "started_at": NOW - 2400, "finished_at": NOW - 600,
                "state": "fail", "verdict": "FAIL"})
            done = home.ak("run", "status")
            self.assertEqual(done.code, 0, done.err)
            self.assertRegex(done.out, rf"(?m)^{run_id} .*\n  × FAIL$")
            self.assertEqual([mark for mark in GONE if mark in done.out], [], done.out)


if __name__ == "__main__":
    unittest.main()
