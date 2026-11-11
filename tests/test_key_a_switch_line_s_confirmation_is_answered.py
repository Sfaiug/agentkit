"""A move ak types into a seat goes through when its harness asks to confirm it.

Claude Code 2.1.322 answers `/model <id>` with a card in its composer's place wherever the
conversation's prompt cache may be warm, and `/effort <level>` with the same card titled `Change
effort level?` where the change misses that cache; `1` takes the move and its composer comes
back.  On 10 Nov 2026 `a apply to all sessions` left every seat it moved in place on that card
until the owner answered each by hand.  ak answers it for a `switch` line of its own whose Enter
went, and a card it typed no such line for is the owner's own move, which it leaves alone.

Black-box: `AK_BIN`, as the popup over a seat and as `ak watch` ticks (tests/fixtures/akbin.py),
the seat's pane tests/fixtures/akpane.py drawing that card after the line that raises it until
`1` arrives, then its empty composer.  Judged by what the pane took and the seat's record."""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
MODEL, EFFORT = "/model claude-fable-5-1", "/effort xhigh"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
# The card at the bottom of a pane 30 rows tall, as 2.1.322 drew it at 86 columns.
CARD = "\n" * 16 + """● ok

✻ Worked for 5s · done 8:04 AM
""" + "▔" * 86 + """
   Switch model?
   Your next response will be slower and use more tokens

   This conversation is cached for the current model. Switching to Sonnet 5.5 means
   the full history gets re-read.

   ❯ 1. Yes, switch to Sonnet 5.5
     2. No, go back

"""
EFFORT_CARD = CARD.replace("Switch model?", "Change effort level?")


def key_line(screen):
    return next((line.rstrip() for line in reversed(screen.split("\n")) if line.strip()), "")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ASwitchLineSConfirmationIsAnswered(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])

    def seat(self, asks, model="opus"):
        return Seat(self.home, SEAT, model=model, asks=asks)

    def standing(self, seat, line):
        """The seat on the card `line` raised, typed and entered before ak answered any."""
        self.home.tmux("send-keys", "-t", seat.pane, "-l", line)
        self.home.tmux("send-keys", "-t", seat.pane, "Enter")
        self.on_card(seat)

    def on_card(self, seat):
        deadline = time.monotonic() + 30
        while "2. No, go back" not in seat.capture():
            self.assertLess(time.monotonic(), deadline, seat.capture())
            time.sleep(0.05)

    def owe(self, seat, *lines):
        """The seat owed those move lines, each `(line, typed)`: its mark kept where typed."""
        self.home.write(f".agentkit/state/seat-{SEAT}.json", {"owed_lines": [
            {"line": line, "switch": True, "pane": seat.pane, "id": str(at),
             **({"typed": seat.mark(line)} if typed else {})}
            for at, (line, typed) in enumerate(lines)]})

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def orchestrator(self):
        path = self.home.path / f".agentkit/state/session-{SEAT}.json"
        return json.loads(path.read_text())["orchestrator"]

    def test_a_move_in_place_types_its_model_then_yes_then_its_effort(self):
        seat = self.seat({"/model ": CARD})
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "␣ mark" in key_line(screen) and "› Opus 5.5" in screen)
        term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        self.on_card(seat)
        self.tick()
        self.assertEqual(seat.typed(), MODEL + "\r1")
        self.tick()
        self.assertEqual(seat.typed(), MODEL + "\r1" + EFFORT + "\r")
        self.assertEqual(self.orchestrator(), "fable")

    def test_a_seat_standing_on_the_card_gets_yes_at_the_next_tick_then_its_effort(self):
        seat = self.seat({"/model ": CARD}, model="fable")
        self.standing(seat, MODEL)
        self.owe(seat, (MODEL, True), (EFFORT, False))
        self.tick()
        self.assertEqual(seat.typed(), MODEL + "\r1")
        self.tick()
        self.assertEqual(seat.typed(), MODEL + "\r1" + EFFORT + "\r")

    def test_the_change_effort_level_card_is_answered_the_same_way(self):
        seat = self.seat({"/effort ": EFFORT_CARD}, model="fable")
        self.standing(seat, EFFORT)
        self.owe(seat, (EFFORT, True))
        self.tick()
        self.assertEqual(seat.typed(), EFFORT + "\r1")

    def test_the_card_on_a_seat_owed_no_typed_switch_line_gets_no_key(self):
        seat = self.seat({"/model ": CARD})
        self.standing(seat, MODEL)      # the owner's own move
        self.owe(seat, (EFFORT, False))
        self.tick()
        self.assertEqual(seat.typed(), MODEL + "\r")


if __name__ == "__main__":
    unittest.main()
