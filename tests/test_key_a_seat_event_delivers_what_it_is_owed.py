"""A move chosen for a seat mid-turn goes in at the event that ends its turn, with no tick.

The owner (13 Nov 2026): "when I switch effort or model or both and right now there is a
question asked in the chat, it is unable to switch then. [...] all edge cases shall be handled,
and the switch should happen as soon as possible."  A move from a seat's `c` while its harness
works owes it its lines and types none of them; the look its Stop starts types them -- the
model, the yes to the card drawn in its composer's place, the effort -- before any tick runs.
A seat owed nothing has nothing typed by its Stop's look.

Black-box: `AK_BIN`, as the popup over a seat (tests/fixtures/akterm.py), Claude's hooks as its
adapter registers them (tests/fixtures/hookdrive.py), and the seat's pane
tests/fixtures/akpane.py drawing what its harness shows after `/model <id>` until `1` arrives.
Judged by what the pane took, the lines the seat's record owes it and ak's processes on it."""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from fixtures.hookdrive import Hooks

SEAT = "acme-fix"
MODEL, EFFORT = "/model claude-fable-5-1", "/effort xhigh"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
CARD = "claude-switch-model-card-pane.txt"
# Claude Code's Stop with no background work in flight.
STOP = {"background_tasks": [], "transcript_path": "", "last_assistant_message": "Done."}
BOUND = 300


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatEventDeliversWhatItIsOwed(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])
        self.hooks = Hooks(self.home)

    def owed(self):
        path = self.home.path / f".agentkit/state/seat-{SEAT}.json"
        return json.loads(path.read_text()).get("owed_lines") if path.exists() else None

    def ak_on(self):
        """ak's processes on the seat: of this Home, naming it, and no tmux server."""
        home, found = f"HOME={self.home.path}".encode(), []
        for entry in Path("/proc").glob("[0-9]*"):
            try:
                env = (entry / "environ").read_bytes().split(b"\0")
                words = (entry / "cmdline").read_bytes().split(b"\0")
                server = (entry / "comm").read_bytes() == b"tmux: server\n"
            except OSError:
                continue
            if home in env and SEAT.encode() in words and not server:
                found.append(int(entry.name))
        return found

    def until(self, holds, said, shown):
        deadline = time.monotonic() + BOUND
        while not holds():
            self.assertLess(time.monotonic(), deadline, said.format(shown()))
            time.sleep(0.1)

    def stopped(self, seat):
        """The seat's turn ends: its prompt is drawn, its Stop fires, and its look is over."""
        seat.show("claude-prompt-pane.txt")
        fired = self.hooks.fire("Stop", STOP, seat=SEAT, pane=seat)
        self.assertEqual(fired.code, 0, fired.out + fired.err)
        self.until(lambda: not self.ak_on(), "still on it: {}", self.ak_on)

    def test_a_move_owed_mid_turn_goes_in_at_its_stop(self):
        seat = Seat(self.home, SEAT, model="opus", screen="claude-working-pane.txt",
                    asks={"/model ": CARD})
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=SEAT, pane=seat,
                                finished=True)
        self.assertEqual(fired.code, 0, fired.out + fired.err)
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", **OFFLINE, "AGENTKIT_SESSION": SEAT})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("› Opus 5.5")
        term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        # the move's own passes find the harness in its turn, type nothing, and are over
        self.until(self.ak_on, "the move's passes never started: {}", self.owed)
        self.until(lambda: not self.ak_on(), "still on it: {}", self.ak_on)
        self.assertEqual([owed["line"] for owed in self.owed()], [MODEL, EFFORT])
        self.assertEqual(seat.typed(), "")
        self.stopped(seat)
        self.assertEqual(seat.typed(), MODEL + "\r1" + EFFORT + "\r")
        self.assertFalse(self.owed())

    def test_a_seat_owed_nothing_has_nothing_typed_at_its_stop(self):
        seat = Seat(self.home, SEAT, model="opus", screen="claude-working-pane.txt")
        self.stopped(seat)
        self.assertEqual(seat.typed(), "")
        self.assertFalse(self.owed())


if __name__ == "__main__":
    unittest.main()
