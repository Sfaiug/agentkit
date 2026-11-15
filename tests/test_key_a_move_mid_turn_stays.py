"""A move that went into a Claude seat mid-turn is not undone by that turn's own replies.

The owner (13 Nov 2026): "When I chose to switch effort or model in ak, all edge cases shall be
handled, and the switch should happen as soon as possible."  Claude Code takes a move's lines
inside a turn (`[switch] midturn`), and stamps each reply of that turn with the effort the turn
began with: one newer than the move moves nothing, and the seat's row and record keep the effort
chosen until a turn begun after the move answers -- at an effort typed inside the seat, which the
record then follows, as before.

Black-box: `AK_BIN`, as the popup over a seat whose turns its hooks begin and end
(tests/fixtures/hookdrive.py), its conversation written where Claude Code keeps it, looked at by
`ak orch list`.  Judged by the seat's record and its row on `c`."""

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
from test_key_effort_followed_from_inside import opus_effort, stamp

SEAT = "acme-fix"
WORKING = "claude-working-pane.txt"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
BOUND = 300     # how long a seat may take to show what ak did, as `Seat.wait_lines` waits


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMoveMidTurnStays(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        fakeadapter.install(self.home, claude="pass", codex="pass")
        self.seat = Seat(self.home, SEAT, screen=WORKING, record={
            "launched": time.time() - 600, "efforts": {"opus": {"effort": "xhigh"}}})
        self.hooks = Hooks(self.home)
        project = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(self.seat.cwd))
        self.conversation = (self.home.path / ".claude/projects" / project
                             / f"{self.seat.record['conversation']}.jsonl")

    def live(self):
        path = self.home.path / f".agentkit/state/seat-{SEAT}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def effort(self):
        path = self.home.path / f".agentkit/state/session-{SEAT}.json"
        return json.loads(path.read_text())["efforts"]["opus"]["effort"]

    def until(self, holds, said):
        deadline = time.monotonic() + BOUND
        while not holds():
            self.assertLess(time.monotonic(), deadline, said())
            time.sleep(0.1)

    def prompted(self, text):
        """The owner's `text` begins a turn, written into the seat's conversation."""
        began = self.hooks.prompt(text, self.seat)
        self.assertEqual(began.code, 0, began.err)

    def answered(self, effort):
        """A reply of the turn running, stamped `effort`, then a look at the seat."""
        with self.conversation.open("a") as conversation:
            conversation.write(json.dumps({"type": "assistant", "timestamp": stamp(time.time()),
                                           "effort": effort,
                                           "message": {"model": "claude-opus-5-5"}}) + "\n")
        looked = self.home.ak("orch", "list")
        self.assertEqual(looked.code, 0, looked.out + looked.err)

    def test_a_reply_of_the_turn_moved_keeps_the_effort_chosen_and_a_later_turn_moves_it(self):
        self.prompted("go")
        self.until(lambda: self.live().get("word") == "working",
                   lambda: f"its turn never began: {self.live()}")
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "esc back" in screen and opus_effort(screen) == "xhigh")
        term.keys("Right", "Space")     # Opus's orchestrator effort, a step up
        self.assertEqual(self.seat.wait_lines(1), ["/effort max"])
        self.until(lambda: not self.live().get("owed_lines"), lambda: "its move is still owed")
        self.assertEqual(self.effort(), "max")

        self.answered("xhigh")
        self.assertEqual(self.effort(), "max")
        term.wait(lambda screen: opus_effort(screen) == "max")

        self.seat.show("claude-prompt-pane.txt")
        ended = self.hooks.fire("Stop", {"background_tasks": []}, seat=SEAT, pane=self.seat)
        self.assertEqual(ended.code, 0, ended.err)
        self.seat.show(WORKING)
        self.prompted("and on")     # after `/effort low` typed inside the seat
        self.answered("low")
        self.assertEqual(self.effort(), "low")
        term.wait(lambda screen: opus_effort(screen) == "low")


if __name__ == "__main__":
    unittest.main()
