"""A seat moved on `c` onto a model whose window is full, or stepped to another effort on one,
switches as any seat does: its lines typed into its harness, nothing said under the rows.

The owner (12 Nov 2026): "Regardless of remaining usage I want to be able to switch model and
effort of any role."  The mark costs nothing; a seat on a spent model reads out of usage and goes
on by itself once it is back.  Black-box: `AK_BIN`, as the popup over a seat on Opus 5.5 whose
pane keeps each line typed into it, its harnesses fakes whose every Claude window is full; fails
against `/bin/false`."""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_seat_switches_in_place import KEYS, OFFLINE, SEAT, key_line, rows


def said(screen):
    """What the screen says under its rows, past agentkit's build: why the last key did nothing."""
    shown = rows(screen)
    under = [at for at, line in enumerate(shown) if line.startswith("  Version ")]
    return [line for line in shown[under[0] + 1:] if line and line != key_line(screen)
            ] if under else []


def row(screen, label):
    """The words of the highlighted row, `label`'s, or []."""
    return next((line.split() for line in rows(screen) if line.startswith(f"› {label}")), [])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SwitchAsksNothingOfUsage(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        full = {"used": 100, "resets_at": int(time.time()) + 86400, "window_secs": 604800}
        fakes["claude"].answer("usage", json.dumps({"meters": [
            {"name": name, **full} for name in ("weekly", "weekly_scoped")], "error": None}))
        akconfig.write(home, ["opus", "fable", "astra"], workers=["opus"])
        self.seat = Seat(home, SEAT, model="opus", record={
            "reviewers": ["astra"], "efforts": {"opus": {"effort": "xhigh"}}})
        self.term = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)

    def test_a_model_whose_window_is_full_is_typed_into_it(self):
        self.term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        screen = self.term.wait(lambda screen: said(screen)
                                or "[●]" in row(screen, "Fable 5.1"))
        self.assertEqual(said(screen), [])
        self.assertEqual(self.seat.wait_lines(2), ["/model claude-fable-5-1", "/effort xhigh"])

    def test_an_effort_step_on_a_model_whose_window_is_full_is_typed_into_it(self):
        self.term.keys("Right", "Space")    # Opus 5.5's effort, one step up from xhigh
        screen = self.term.wait(lambda screen: said(screen)
                                or "max" in row(screen, "Opus 5.5"))
        self.assertEqual(said(screen), [])
        self.assertEqual(self.seat.wait_lines(1), ["/effort max"])


if __name__ == "__main__":
    unittest.main()
