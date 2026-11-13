"""A seat moved on `c` whose model has left the config restarts only over an input field ak
read empty, through the harness its pane runs; text it cannot read or lift stays with that harness.

ak answered such a seat's text kept without reading its field, and the restart took the text
with the old harness; a capture of its pane that failed it took for a field read empty.
Black-box: `AK_BIN`, as the popup over a seat whose record names a model the config no longer
has, its pane tests/fixtures/akpane.py running as `claude`.  Judged by the pane's process, what
it shows and the seat's record."""

import json
import shlex
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
DRAFT = "and add these posts"
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def key_line(screen):
    return next((line.rstrip() for line in reversed(screen.split("\n")) if line.strip()), "")


# "always the input in the text field must be preserved" [12 Nov 2026]
@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SwitchLeavesTextItCannotLift(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])
        self.seat = Seat(self.home, SEAT, record={"orchestrator": "retired"}, program="claude")

    def process(self):
        return self.home.tmux("display-message", "-p", "-t", self.seat.pane, "#{pane_pid}").out

    def orchestrator(self):
        path = self.home.path / f".agentkit/state/session-{SEAT}.json"
        return json.loads(path.read_text())["orchestrator"]

    def move(self, settled):
        """The seat moved to Opus 5.5 on `c`, the restart taken: the screen once `settled`."""
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        term.keys("Space")             # Opus 5.5's orchestrator mark
        term.wait(f"Restart {SEAT} on Opus 5.5?")
        term.keys("Down", "Enter")     # Move
        return term.wait(settled)

    def stays(self):
        """Text typed into its field stays there, and the seat on the harness it runs, through
        a move."""
        self.home.tmux("send-keys", "-t", self.seat.pane, "-l", DRAFT)
        deadline = time.monotonic() + 30
        while f"❯ {DRAFT}" not in self.seat.capture():     # drawn before ak reads the field
            self.assertLess(time.monotonic(), deadline, self.seat.capture())
            time.sleep(0.05)
        ran = self.process()
        self.move(f"{SEAT} stays on retired: the text in its input field could not be kept")
        self.assertEqual((self.process(), self.orchestrator()), (ran, "retired"))
        self.assertIn(f"❯ {DRAFT}", self.seat.capture())

    def test_text_in_its_field_stays_with_the_harness_it_runs(self):
        self.stays()

    def test_text_in_a_field_ak_cannot_capture_stays_too(self):
        tmux = (self.home.bin / "tmux").rename(self.home.bin / "tmux-shim")
        self.home.fake("tmux", "#!/bin/sh\nfor a do [ \"$a\" = capture-pane ] && exit 1; done\n"
                               f'exec {shlex.quote(str(tmux))} "$@"\n')
        self.stays()

    def test_a_field_read_empty_moves_it(self):
        ran = self.process()
        self.move(lambda screen: key_line(screen) == KEYS and self.orchestrator() == "opus")
        self.assertNotEqual(self.process(), ran)


if __name__ == "__main__":
    unittest.main()
