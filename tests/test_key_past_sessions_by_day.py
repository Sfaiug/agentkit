"""The past sessions screen, `p`, black-box: `AK_BIN` in a terminal (fixtures/akterm.py), its clock
a time zone where it is past noon, and a fake adapter reopening a seat into a harness saying so."""

import os
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

TZ = f"AKT{time.gmtime().tm_hour - 12:+d}"      # past noon, so today at 10:00 has been
os.environ["TZ"] = TZ
time.tzset()
ADAPTER = "#!/bin/sh\nprintf '%s' \"sh -c 'echo reopened $4; exec sleep 300'\"\n"
KEYS = "  ↑↓←→ move   ⏎ reopen   x remove   esc back"
DAYS = ("today", "yesterday", "this week", "earlier")


def at(days, hour, minute=0):
    return time.mktime((*time.localtime(time.time() - days * 86400)[:3], hour, minute, 0, 0, 0, -1))


SEATS = {"fix-api": at(0, 10), "fix-web": at(1, 9), "add-docs": at(3, 15, 30),
         "old-search": at(10, 8)}
SHOWN = ("10:00", "09:00", time.strftime("%a 15:30", time.localtime(SEATS["add-docs"])),
         time.strftime("%-d %b", time.localtime(SEATS["old-search"])))


def opened(test):
    """The four seats of acme closed, fix-api's plan 3 of 4 done, and the past screen up."""
    home = Home()
    test.addClassCleanup(home.close)
    checkout = home.path / "code/acme"
    checkout.mkdir(parents=True)
    assert home.run("git", "init", "-q", str(checkout)).code == 0
    for name, closed in SEATS.items():
        home.write(f".agentkit/state/session-{name}.json", {
            "orchestrator": "fable", "workers": ["fable"], "cwd": str(checkout),
            "repo": str(checkout), "created": int(closed) - 3600, "conversation": f"conv-{name}",
            "id_source": "launcher", "resumable": True, "session_title": name})
        home.write(f".agentkit/state/seat-{name}.json",
                   {"stopped_at": closed, "closed_by_owner": True})
    home.write(".agentkit/state/plan-fix-api.md", "- [x] Ship the docs site. Then the search.\n"
               "- [x] Fix a typo\n- [x] Add a test\n- [ ] Search\n")
    home.write("adapters/claude.sh", ADAPTER).chmod(0o755)
    menu = Terminal(home, size=(100, 30), env={"AGENTKIT_ADAPTER_DIR": home.path / "adapters",
                                               "TZ": TZ})
    menu.wait(lambda screen: "p past" in screen)
    menu.keys("p")
    return home, menu, menu.wait(lambda screen: KEYS in screen and "3 of 4" in screen
                                 and screen.startswith("agentkit · past sessions"))


def lines(screen):
    return [line.rstrip() for line in screen.rstrip().split("\n")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home, menu, cls.screen = opened(cls)
        record = home.path / ".agentkit/state/session-fix-web.json"
        menu.keys("Down", "x")
        cls.card = menu.wait("Remove fix-web from past sessions?")
        menu.keys("Enter")
        cls.kept = menu.wait(lambda screen: KEYS in screen and "Remove fix-web" not in screen)
        cls.records = [record.exists()]
        menu.keys("x"), menu.wait("Remove fix-web from past sessions?"), menu.keys("Down", "Enter")
        cls.removed = menu.wait(lambda screen: KEYS in screen and "fix-web" not in screen)
        cls.records.append(record.exists())

    def test_numbered_from_1_newest_closed_first_under_the_day_each_closed(self):
        shown = lines(self.screen)
        self.assertEqual([line for line in shown if line in DAYS], list(DAYS))
        for number, (name, closed, day) in enumerate(zip(SEATS, SHOWN, DAYS), 1):
            row = next(n for n, line in enumerate(shown) if f"  {name} " in line)
            self.assertRegex(shown[row], rf"^. {number}  {name}\s+acme\s+.*\s{closed}$")
            self.assertEqual(shown[row - 1], day)
        self.assertEqual(shown[-1], KEYS)

    def test_a_plan_shows_its_count_and_the_highlight_opens_its_first_sentence(self):
        shown = lines(self.screen)
        self.assertRegex(shown[3], r"^› 1  fix-api .*━+─+ 3 of 4 ")
        self.assertEqual(shown[4].strip(), "Ship the docs site.")
        self.assertRegex(shown[6], r"^  2  fix-web\s+acme  no plan ")

    def test_x_asks_first_keep_leaves_it_listed_and_remove_takes_it_off(self):
        card = lines(self.card)
        at = card.index("  Remove fix-web from past sessions?")
        self.assertEqual(card[at + 1:at + 4],
                         ["  It can no longer be reopened.", "› ✓ Keep", "  ✗ Remove"])
        self.assertIn("2  fix-web", self.kept)
        self.assertIn("2  add-docs", self.removed)
        self.assertEqual(self.records, [True, False])       # kept, then removed


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Reopening(unittest.TestCase):
    def test_2_and_enter_on_row_2_each_reopen_the_seat_closed_yesterday(self):
        for keys in (("2",), ("Down", "Enter")):
            with self.subTest(keys=keys):
                _home, menu, _screen = opened(self)
                menu.keys(*keys)
                menu.wait("reopened conv-fix-web")


if __name__ == "__main__":
    unittest.main()
