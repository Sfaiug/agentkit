"""A line's Enter on its way into a seat gets no second one from another pass that holds its mark.

A seat's lines have more than one teller -- a move's own process, the seat's hook look, the
tick -- and one sends a line's Enter and lets go of the seat before its harness has drawn what
that Enter did.  On 14 Nov 2026, on a loaded host, a Claude seat's hook look read the
`/effort` line a move had just entered still in its composer, and a second Enter went in after
it.  A pass that holds a line's mark gives it an Enter only where the line stays as long as the
pass that typed it waits for its own.

Black-box: `AK_BIN`, as the seat's hook looks (tests/fixtures/hookdrive.py), the seat's pane
tests/fixtures/akpane.py drawing a working screen whose harness took the line and its Enter
and draws its composer empty only LATE seconds after the look publishes the seat's word, its
next step being the seat's lines.  Judged by what the pane took."""

import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import FIXTURES, Seat
from fixtures.hookdrive import Hooks

SEAT = "acme-fix"
EFFORT = "/effort xhigh"
WORKING = (FIXTURES / "claude-working-pane.txt").read_text(encoding="utf-8")
LATE = 2.5      # seconds past the look's word: past its first read of the lines, inside its wait


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnEnterOnItsWayGetsNoSecond(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])

    def test_a_look_holding_the_mark_adds_no_enter_to_one_its_harness_has_yet_to_draw(self):
        seat = Seat(self.home, SEAT, screen=WORKING.replace("❯\u00a0\n", f"❯ {EFFORT}\n"))
        hooks = Hooks(self.home)
        self.home.tmux("send-keys", "-t", seat.pane, "-l", EFFORT)
        self.home.tmux("send-keys", "-t", seat.pane, "Enter")
        self.assertEqual(seat.wait_lines(1), [EFFORT])
        self.home.write(f".agentkit/state/seat-{SEAT}.json", {"owed_lines": [
            {"line": EFFORT, "switch": True, "pane": seat.pane, "id": "0",
             "typed": seat.mark(EFFORT)}]})
        looked = threading.Event()
        drawn = threading.Thread(target=self.drawn, args=(seat, looked))
        self.addCleanup(drawn.join)
        self.addCleanup(looked.set)
        drawn.start()
        fired = hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=SEAT, pane=seat,
                           finished=True)
        looked.set()
        self.assertEqual(fired.code, 0, fired.err)
        self.assertEqual(seat.typed(), EFFORT + "\r")
        self.assertEqual(seat.lines(), [EFFORT])

    def drawn(self, seat, looked):
        """The harness draws its composer empty LATE seconds after the look publishes the seat's
        word; nothing once the look is over."""
        path = self.home.path / f".agentkit/state/seat-{SEAT}.json"
        while not json.loads(path.read_text()).get("word"):
            if looked.wait(0.05):
                return
        time.sleep(LATE)
        seat.show(WORKING)


if __name__ == "__main__":
    unittest.main()
