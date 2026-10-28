"""Every key line names what Enter does where the highlight is, and nothing of another screen.

The owner (27 Oct 2026): "everywhere enter is for like opening, new page and stuff like that,
and space should be select / unselect ... Be thorough. I want it to be consistent."  On the ak
screen Enter opens the highlighted seat, `⏎ open`, and on the row `n` makes it starts one,
`⏎ start`.  A yes-or-no card has a key line of its own, Enter named for the answer highlighted
-- `⏎ keep` on Keep, `⏎ stop` or `⏎ remove` on the other -- whatever screen it is asked on.  A
field typed in on `c`'s Discord page saves on Enter, and the arrows move nothing there.
Black-box: `AK_BIN`'s menu in a person's terminal (tests/fixtures/akterm.py) beside seats of
tests/fixtures/akseat.py, the popup over one of them, a second one the owner stopped.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

POPUP_KEYS = "  ↑↓←→ move   ⏎ open   n new   x stop   p past   c config   esc leave"
ROW_KEYS = "  ⏎ start   tab models   esc back"
KEEP, STOP, REMOVE = (f"  ↑↓←→ move   ⏎ {word}   esc back"
                      for word in ("keep", "stop", "remove"))
PAGED = "←  1 / "              # the page mark leading a key line
NOW = int(time.time())


def key_line(screen):
    return next((line.rstrip() for line in reversed(screen.split("\n")) if line.strip()), "")


def ends(keys):
    """A test of the screen: its key line is `keys`."""
    return lambda screen: key_line(screen) == keys


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EnterNamedEverywhere(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        Seat(home, "atoll-fix", screen="claude-working-pane.txt", record={"created": NOW - 900})
        home.write(".agentkit/state/session-beta.json", {
            "orchestrator": "fable", "workers": ["fable"], "cwd": str(home.path),
            "created": NOW - 90000, "conversation": "conv-beta", "id_source": "launcher",
            "resumable": True, "session_title": "beta"})
        home.write(".agentkit/state/seat-beta.json",
                   {"stopped_at": NOW - 9000, "closed_by_owner": True})
        self.menu = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"AGENTKIT_SESSION": "atoll-fix"})
        self.menu.wait(lambda screen: "atoll-fix" in screen and ends(POPUP_KEYS)(screen))

    def test_the_ak_screen_opens_and_the_new_row_starts(self):
        self.menu.keys("n")
        self.menu.wait(ends(ROW_KEYS))
        self.menu.keys("Escape")
        self.menu.wait(ends(POPUP_KEYS))

    def test_a_card_names_the_answer_enter_gives_and_nothing_of_the_screen_behind(self):
        self.menu.keys("x")
        self.menu.wait(lambda screen: "› ✓ Keep" in screen and ends(KEEP)(screen))
        self.menu.keys("Down")
        self.menu.wait(lambda screen: "› ✗ Stop" in screen and ends(STOP)(screen))
        self.menu.keys("Escape")
        self.menu.wait(ends(POPUP_KEYS))
        self.menu.keys("p")
        self.menu.wait(lambda screen: "beta" in screen and key_line(screen).endswith("esc back"))
        self.menu.keys("x")
        self.menu.wait(lambda screen: "Remove beta from past sessions?" in screen
                       and ends(KEEP)(screen))
        self.menu.keys("Down")
        self.menu.wait(lambda screen: "› ✗ Remove" in screen and ends(REMOVE)(screen))
        self.menu.keys("Escape")

    def test_a_field_typed_in_on_discord_saves_on_enter(self):
        self.menu.keys("c")
        for _ in range(30):         # down the matrix, a row at a time, onto Discord
            shown = self.menu.wait(lambda screen: "\n› " in screen)
            if "\n› Discord" in shown:
                break
            self.menu.keys("Down")
            self.menu.wait(lambda screen: screen != shown)
        self.menu.keys("Enter")
        self.menu.wait(lambda screen: "\n› Mention" in screen)
        self.menu.keys("Enter")
        self.menu.wait(ends("  ⏎ save   esc back"))

    def test_a_card_over_a_screen_of_pages_turns_none(self):
        # past sessions and seats both more than a page: the card shows no `←  1 / N  →`
        for number in range(12):
            name = f"past-{number:02d}"
            self.home.write(f".agentkit/state/session-{name}.json", {
                "orchestrator": "fable", "workers": ["fable"], "cwd": str(self.home.path),
                "created": NOW - 90000, "session_title": name})
            self.home.write(f".agentkit/state/seat-{name}.json",
                            {"stopped_at": NOW - 9000 - number, "closed_by_owner": True})
        for number in range(10):
            Seat(self.home, f"acme-{number:02d}", screen="claude-working-pane.txt")
        self.menu.keys("Escape")
        menu = Terminal(self.home, "attach", "--overlay", size=(100, 16),
                        env={"AGENTKIT_SESSION": "atoll-fix"})
        menu.wait(lambda screen: PAGED in key_line(screen) and "x stop" in screen)
        menu.keys("x")
        menu.wait(lambda screen: "Stop atoll-fix" in screen and ends(KEEP)(screen))
        menu.keys("Escape")
        menu.wait(lambda screen: PAGED in key_line(screen) and "p past" in screen)
        menu.keys("p")
        menu.wait(lambda screen: PAGED in key_line(screen) and "x remove" in screen)
        menu.keys("x")
        menu.wait(lambda screen: "from past sessions?" in screen and ends(KEEP)(screen))
        menu.keys("Escape")


if __name__ == "__main__":
    unittest.main()
