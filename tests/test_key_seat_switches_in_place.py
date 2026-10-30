"""A seat moved on `c` to another model of its harness and login is typed `/model <id>` then
`/effort <level>` into its harness's process, whichever window it shows, asking nothing, and keeps
its conversation; a move to another harness's model, or once that process's pane is gone, asks,
and restarts it.

The owner (30 Oct 2026): "if its a different harness, then yes, a restart must happen, but if
it is merely a model change or effort, or both, then the change should be able to happen inside
the session, without any need to restart."  Black-box: `AK_BIN`, as the popup over a seat on Opus
5.5 whose pane keeps each line typed into it, its harnesses fakes; fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatSwitchesInPlace(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fakes = fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, ["opus", "fable", "astra"], workers=["opus"])
        self.seat = Seat(home, SEAT, model="opus", record={"reviewers": ["astra"]})
        self.path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        self.term = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)

    def pid(self):
        return self.home.tmux("display-message", "-p", "-t", self.seat.pane,
                              "#{pane_pid}").out.strip()

    def record(self):
        return json.loads(self.path.read_text())

    def orchestrator(self):
        return self.record()["orchestrator"]

    def test_another_model_of_its_harness_is_typed_into_it_asking_nothing(self):
        self.home.tmux("new-window", "-t", f"={SEAT}:", "sleep 86400")   # the one it shows
        pid = self.pid()
        self.term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        self.assertEqual(self.seat.wait_lines(2), ["/model claude-fable-5-1", "/effort xhigh"])
        screen = self.term.wait(lambda screen: key_line(screen) == KEYS
                                and self.orchestrator() == "fable")
        self.assertNotIn(f"  Restart {SEAT} on Fable 5.1?", rows(screen))
        self.assertEqual(self.pid(), pid)
        self.assertEqual(self.fakes["claude"].calls("interactive"), [])
        self.assertEqual(self.record()["conversation"], f"conv-{SEAT}")

    def test_another_harness_s_model_asks_and_restarts_it(self):
        self.fakes["codex"].answer("interactive", "", 3, given=["new"])  # Codex takes no id of ours
        pid = self.pid()
        self.term.keys("Down", "Down", "Space")     # GPT-6-Astra's orchestrator mark
        self.term.wait(lambda screen: f"  Restart {SEAT} on GPT-6-Astra?" in rows(screen)
                       and "  ✗ Move" in rows(screen))
        self.term.keys("Down", "Enter")
        self.term.wait(lambda _: self.pid() != pid)
        self.assertEqual(self.orchestrator(), "astra")
        self.assertEqual(self.seat.lines(), [])

    def test_a_seat_whose_harness_s_pane_is_gone_asks(self):
        self.home.tmux("new-window", "-d", "-t", f"={SEAT}:", "sleep 86400")
        self.home.tmux("kill-pane", "-t", self.seat.pane)
        self.term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        self.term.wait(lambda screen: f"  Restart {SEAT} on Fable 5.1?" in rows(screen))
        self.assertEqual(self.orchestrator(), "opus")


if __name__ == "__main__":
    unittest.main()
