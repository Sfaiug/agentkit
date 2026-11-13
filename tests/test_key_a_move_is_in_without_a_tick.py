"""A move ak types into a seat is in within seconds, and the menu does not wait for it.

The owner (10 Nov 2026): "I just changed all active sessions orch using ak, but they are unable to
automatically approve this pop up in claude code, even though ak should. Fix this."  On a real
Claude Code 2.1.322 seat (11 Nov 2026) a move to another model and effort took four passes --
`/model <id>`, the yes to the card drawn in its composer's place, `/effort <level>`, the composer
read back -- and every pass after a move's own first was the tick's, three minutes apart.  Now a
move's lines get their passes at once, behind the menu: from a seat's `c`, and from `a apply to
all sessions` over several seats, with no tick.  A harness that takes the line and draws no
composer after it keeps the line owed with its mark, nothing of ak's left on it, and the next
tick to find its composer back delivers it.

Black-box: `AK_BIN`, as the popup over a seat and the menu (tests/fixtures/akterm.py) and as
`ak watch` ticks (tests/fixtures/akbin.py), the seat's pane tests/fixtures/akpane.py drawing what
its harness shows after `/model <id>` until `1` arrives, then its empty composer.  Judged by what
the pane took, the lines the seat's record owes it and the processes on the machine."""

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
CARD = "claude-switch-model-card-pane.txt"
# A harness that took `/model <id>` and draws no composer, nor anything it asks.
TAKING = "\n" * 20 + "● ok\n\n✻ Switching model\n" + "\n" * 7
# How long a seat may take to show what ak did, as long as `Seat.wait_lines` waits.
BOUND = 300


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMoveIsInWithoutATick(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")

    def terminal(self, *argv, **env):
        term = Terminal(self.home, *argv, size=(100, 30), env={"NO_COLOR": "1", **OFFLINE, **env})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        return term

    def move_from_c(self, asks):
        """`SEAT`, on Opus 5.5 and asking `asks`, moved to Fable 5.1 on its popup's `c`."""
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])
        seat = Seat(self.home, SEAT, model="opus", asks=asks)
        term = self.terminal("attach", "--overlay", AGENTKIT_SESSION=SEAT)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "␣ mark" in key_line(screen) and "› Opus 5.5" in screen)
        term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        return seat

    def owed(self, name):
        path = self.home.path / f".agentkit/state/seat-{name}.json"
        return json.loads(path.read_text()).get("owed_lines") if path.exists() else None

    def moved(self, seat):
        """What the seat took once both its lines are in and it is owed nothing."""
        seat.wait_lines(2)
        self.until(lambda: not self.owed(seat.name), f"{seat.name} still owes {{}}",
                   lambda: self.owed(seat.name))
        return seat.typed()

    def ak_on(self, name):
        """ak's processes on that seat: of this Home, naming it, and no tmux server."""
        home, found = f"HOME={self.home.path}".encode(), []
        for entry in Path("/proc").glob("[0-9]*"):
            try:
                env = (entry / "environ").read_bytes().split(b"\0")
                words = (entry / "cmdline").read_bytes().split(b"\0")
                server = (entry / "comm").read_bytes() == b"tmux: server\n"
            except OSError:
                continue
            if home in env and name.encode() in words and not server:
                found.append(int(entry.name))
        return found

    def until(self, holds, said, shown, bound=BOUND):
        deadline = time.monotonic() + bound
        while not holds():
            self.assertLess(time.monotonic(), deadline, said.format(shown()))
            time.sleep(0.1)

    def test_a_move_from_c_types_its_model_the_yes_and_its_effort(self):
        seat = self.move_from_c({"/model ": CARD})
        self.assertEqual(self.moved(seat), MODEL + "\r1" + EFFORT + "\r")

    def test_a_over_two_seats_types_each_its_three(self):
        akconfig.write(self.home, ["fable", "opus"], workers=["fable"])
        seats = [Seat(self.home, name, model="opus", asks={"/model ": CARD})
                 for name in ("acme-api", "acme-web")]
        term = self.terminal()
        term.wait("c config")
        term.keys("c")
        term.wait(lambda screen: "a apply to all sessions" in key_line(screen))
        term.keys("a")
        term.wait(lambda screen: "  × Apply" in rows(screen))
        term.keys("Down", "Enter")
        for seat in seats:
            self.assertEqual(self.moved(seat), MODEL + "\r1" + EFFORT + "\r")

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_harness_drawing_no_composer_keeps_the_line_for_the_tick(self):
        seat = self.move_from_c({"/model ": TAKING})
        self.until(lambda: (self.owed(SEAT) or [{}])[0].get("typed"), "never typed: {}",
                   lambda: self.owed(SEAT))
        self.until(lambda: not self.ak_on(SEAT), "still on it: {}", lambda: self.ak_on(SEAT))
        self.assertEqual([(owed["line"], owed.get("typed")) for owed in self.owed(SEAT)],
                         [(MODEL, seat.mark(MODEL)), (EFFORT, None)])
        self.home.tmux("send-keys", "-t", seat.pane, "1")     # its composer comes back
        self.until(lambda: "❯" in seat.capture(), "no composer:\n{}", seat.capture)
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(seat.lines(), [MODEL, EFFORT])
        self.assertFalse(self.owed(SEAT))


if __name__ == "__main__":
    unittest.main()
