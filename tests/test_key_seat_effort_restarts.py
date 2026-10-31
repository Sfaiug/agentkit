"""On a seat's `c`, a step of its orchestrator's effort is typed into the harness running in
its pane, asking nothing (orch.switch_lines); where that harness has ended it asks first, and
`Restart` restarts the seat's harness at it; Esc changes nothing.

The owner (24 Oct 2026), about the orchestrator: "it should ask me to confirm. As this restarts
the session."  Black-box: the program `AK_BIN` names, as the popup over a seat on Opus 5.5 at
`xhigh` (tests/fixtures/akseat.py), in a person's terminal (tests/fixtures/akterm.py), its
harnesses the fakes of tests/fixtures/fakeadapter.py, judged by what the terminal shows, the
seat's record and the launches its harness is asked for; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
ASK = f"  Restart {SEAT} on Opus 5.5 at max?"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatEffortRestarts(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fakes = fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, ["opus", "astra"], workers=["opus"])
        self.seat = Seat(home, SEAT, model="opus",
                         record={"reviewers": ["astra"], "efforts": {"opus": {"effort": "xhigh"}}})
        self.path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        self.term = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)

    def asked(self):
        """Space on the orchestrator's effort, and the card it asks on, nothing changed yet."""
        self.home.tmux("respawn-pane", "-k", "-t", self.seat.pane, "true")   # its harness ends
        self.term.wait(lambda _: self.home.tmux("display-message", "-p", "-t", self.seat.pane,
                                                "#{pane_dead}").out.strip() == "1")
        record, launched = self.path.read_bytes(), self.launches()
        self.term.keys("Right", "Space")
        self.term.wait(lambda screen: ASK in lines(screen) and "› ✓ Keep" in lines(screen)
                       and "  ✗ Restart" in lines(screen))
        self.assertEqual((self.path.read_bytes(), self.launches()), (record, launched))
        return record, launched

    def launches(self):
        return self.fakes["claude"].calls("interactive")

    def test_a_step_types_only_its_effort_into_its_running_harness(self):
        self.term.keys("Right", "Space")
        self.assertEqual(self.seat.wait_lines(1), ["/effort max"])
        self.term.wait(lambda screen: any(line.lstrip("› ").startswith("Opus 5.5")
                                          and line.split()[5] == "max" for line in lines(screen)))
        self.assertNotIn(ASK, lines(self.term.screen()))
        self.assertEqual(self.launches(), [])

    def test_esc_on_the_card_changes_nothing(self):
        record, launched = self.asked()
        self.term.keys("Escape")
        self.term.wait(lambda screen: key_line(screen) == KEYS.replace("mark", "step") and ASK not in lines(screen))
        time.sleep(1)       # a restart, were one under way, would have begun
        self.assertEqual((self.path.read_bytes(), self.launches()), (record, launched))

    def test_restart_launches_the_seat_s_harness_at_the_step(self):
        _, launched = self.asked()
        self.term.keys("Down", "Enter")
        deadline = time.monotonic() + 30
        while len(self.launches()) == len(launched):
            self.assertLess(time.monotonic(), deadline, "the seat's harness was never launched")
            time.sleep(0.1)
        self.assertEqual(self.launches()[-1]["argv"][:2], ["claude-opus-5-5", "max"])
        # the open screen shows the record as the restart left it, once that restart is over
        self.term.wait(lambda screen: any(line.lstrip("› ").startswith("Opus 5.5")
                                          and line.split()[5] == "max" for line in lines(screen)))
        self.assertEqual(json.loads(self.path.read_text())["efforts"]["opus"]["effort"], "max")


if __name__ == "__main__":
    unittest.main()
