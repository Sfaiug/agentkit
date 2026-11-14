"""A move chosen while a Claude seat works goes into that turn: the switch is as soon as it can be.

The owner (13 Nov 2026): "When I chose to switch effort or model in ak, all edge cases shall be
handled, and the switch should happen as soon as possible."  Claude Code 2.1.323 takes `/model`
and `/effort` typed while a tool runs, into the composer it draws empty there, `/model` asking
its card in that composer's place as at its prompt, and the turn's next response is the new
model's.  So a harness whose adapter says so (`[switch] midturn`) has a move's lines typed in a
turn, its card answered, with no tick and no Stop between them -- never onto the owner's text or
under a question -- and the turn goes on as it was; any other keeps them until its prompt.

Black-box: `AK_BIN`, as the popup over a seat whose turn its hook began
(tests/fixtures/hookdrive.py) and as `ak watch` ticks, the seat's pane tests/fixtures/akpane.py
drawing a working screen, the card over it after `/model <id>` until `1` arrives.  Judged by what
the pane took and what the seat's records hold."""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat
from fixtures.akterm import SERVER, Terminal
from fixtures.hookdrive import Hooks

SEAT = "acme-fix"
MODEL, EFFORT = "/model claude-fable-5-1", "/effort xhigh"
LUNA = "/model gpt-5.6-luna --reasoning=high"
WORKING = "claude-working-pane.txt"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
BOUND = 300     # how long a seat may take to show what ak did, as `Seat.wait_lines` waits


def on_card(working, card):
    """`working`'s screen with `card`'s card drawn in its composer's place, from the rule over
    the composer down, the spinner above it standing."""
    rows = (FIXTURES / working).read_text(encoding="utf-8").split("\n")
    drawn = (FIXTURES / card).read_text(encoding="utf-8").split("\n")
    top = next(at for at, row in enumerate(rows) if row.startswith("─"))
    return "\n".join(rows[:top] + drawn[next(at for at, row in enumerate(drawn)
                                             if row.startswith("▔")):])


def key_line(screen):
    return next((line.rstrip() for line in reversed(screen.split("\n")) if line.strip()), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClaudeSeatSwitchesMidTurn(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")

    def moved(self, screen, *, harness="claude"):
        """`SEAT`, in a turn showing `screen`, moved on its popup's `c` to the model under its
        own: Claude's, its turn begun by its hook and no Stop since, and Codex's."""
        if harness == "claude":
            akconfig.write(self.home, ["opus", "fable"], workers=["opus"])
            seat = Seat(self.home, SEAT, model="opus", screen=screen,
                        asks={"/model ": on_card(WORKING, "claude-switch-model-card-pane.txt")})
            began = Hooks(self.home).fire("UserPromptSubmit", {"prompt": "go"}, seat=SEAT,
                                          pane=seat)
            self.assertEqual(began.code, 0, began.err)
        else:
            akconfig.write(self.home, {"astra": {}, "luna": {"harness": "codex",
                                                             "model": "gpt-5.6-luna"}})
            seat = Seat(self.home, SEAT, model="astra", screen=screen, composer="›")
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "␣ mark" in key_line(screen))
        self.until(lambda: self.turn()[0], lambda: "its word never published")
        self.was = self.turn()
        term.keys("Down", "Space")     # the other model's orchestrator mark
        return seat

    def turn(self):
        """The seat's word and when its turn began, as its record holds them."""
        path = self.home.path / f".agentkit/state/seat-{SEAT}.json"
        live = json.loads(path.read_text()) if path.exists() else {}
        return live.get("word"), live.get("turn_began")

    def owed(self):
        path = self.home.path / f".agentkit/state/seat-{SEAT}.json"
        return [(owed["line"], owed.get("typed")) for owed in
                (json.loads(path.read_text()).get("owed_lines") or [])] if path.exists() else []

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

    def until(self, holds, said):
        deadline = time.monotonic() + BOUND
        while not holds():
            self.assertLess(time.monotonic(), deadline, said())
            time.sleep(0.1)

    def kept(self, seat, *lines):
        """The move's own passes over, the seat took nothing and still owes `lines` untyped."""
        self.until(self.owed, lambda: "never owed its move")
        self.until(lambda: not self.ak_on(), lambda: f"still on it: {self.ak_on()}")
        self.assertEqual(seat.typed(), "")
        self.assertEqual(self.owed(), [(line, None) for line in lines])

    def test_a_move_mid_turn_types_its_model_the_yes_and_its_effort_at_once(self):
        seat = self.moved(WORKING)
        self.assertEqual(seat.wait_lines(2), [MODEL, EFFORT])
        self.until(lambda: not self.owed(), lambda: f"still owes {self.owed()}")
        self.assertEqual(seat.typed(), MODEL + "\r1" + EFFORT + "\r")
        self.assertEqual(self.turn(), self.was)

    def test_a_question_up_in_the_turn_gets_nothing(self):
        self.kept(self.moved("claude-question-pane.txt"), MODEL, EFFORT)

    def test_the_owner_s_text_in_the_composer_gets_nothing(self):
        self.kept(self.moved("claude-draft-while-working-pane.txt"), MODEL, EFFORT)

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_harness_without_midturn_keeps_its_line_until_its_prompt(self):
        seat = self.moved("codex-working-pane.txt", harness="codex")
        self.kept(seat, LUNA)
        seat.show("codex-prompt-pane.txt")
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(seat.lines(), [LUNA])


if __name__ == "__main__":
    unittest.main()
