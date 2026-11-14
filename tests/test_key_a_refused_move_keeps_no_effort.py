"""A move in place that fails leaves the model it was to run on its config's effort: a seat on
Opus 5.5 moved on `c` to Fable 5.1 while the lines owed to its harness cannot be written stays on
Opus, and moved there again once Fable's config effort is low is typed `/effort low`, never the
effort Fable's entry held when the move failed.

Black-box: `AK_BIN`, as the popup over a seat whose pane keeps each line typed into it, its
harness a fake (tests/fixtures/akpane.py), the file its live state is copied through a directory
so no line owed to it can be written (as tests/test_key_tick_time_is_visible.py makes a seat's
record unwritable); fails against `/bin/false`."""

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
class ARefusedMoveKeepsNoEffort(unittest.TestCase):
    def test_the_model_a_failed_move_was_to_run_moves_later_at_its_config_effort(self):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, ["opus", "fable"], workers=["opus"])
        seat = Seat(home, SEAT, model="opus")
        record = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        blocked = home.path / ".agentkit" / "state" / f"seat-{SEAT}.tmp"
        blocked.mkdir()
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        term.keys("Down", "Space")      # Fable 5.1's orchestrator mark
        term.wait(lambda screen: "session:" in screen)
        self.assertEqual(json.loads(record.read_text())["orchestrator"], "opus")
        blocked.rmdir()
        akconfig.write(home, {"opus": {}, "fable": {"effort": "low"}}, workers=["opus"])
        term.keys("Escape")
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        term.keys("Down", "Space")
        self.assertEqual(seat.wait_lines(2), ["/model claude-fable-5-1", "/effort low"])


if __name__ == "__main__":
    unittest.main()
