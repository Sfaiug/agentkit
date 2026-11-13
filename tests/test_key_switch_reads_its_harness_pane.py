"""A seat moved on `c` is read, kept and restarted at its harness's own pane, whichever window
of its session the owner has selected: an empty field in another window lets no restart take the
text left unsent in the harness's.

ak read the selected window's empty field as the seat's and respawned the harness's pane, losing
its text.  Black-box: `AK_BIN`, as the popup over a seat whose record names a model the config no
longer has, its pane tests/fixtures/akpane.py running as `claude`, and a second window selected,
the same program showing an empty field.  Judged by the harness pane's process, what it shows and
the seat's record."""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import FIXTURES, Seat
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
class SwitchReadsItsHarnessPane(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])
        self.seat = Seat(self.home, SEAT, record={"orchestrator": "retired"}, program="claude")

    def wait(self, pane, text):
        deadline = time.monotonic() + 30
        while text not in self.home.tmux("capture-pane", "-p", "-t", pane).out:
            self.assertLess(time.monotonic(), deadline, self.seat.capture())
            time.sleep(0.05)

    def process(self):
        return self.home.tmux("display-message", "-p", "-t", self.seat.pane, "#{pane_pid}").out

    def orchestrator(self):
        path = self.home.path / f".agentkit/state/session-{SEAT}.json"
        return json.loads(path.read_text())["orchestrator"]

    def test_an_empty_field_in_the_selected_window_restarts_no_harness_holding_text(self):
        self.home.tmux("send-keys", "-t", self.seat.pane, "-l", DRAFT)
        self.wait(self.seat.pane, f"❯ {DRAFT}")
        panes = self.home.root / "panes"
        (panes / "other.txt").write_text((FIXTURES / "claude-prompt-pane.txt").read_text())
        other = self.home.tmux("new-window", "-t", f"={SEAT}:", "-P", "-F", "#{pane_id}",
                               shlex.join([sys.executable, str(self.seat.program),
                                           str(panes / "other.txt"), str(panes / "other.typed"),
                                           "❯"])).out.strip()
        self.wait(other, "❯")
        ran = self.process()
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
        term.wait(f"{SEAT} stays on retired: the text in its input field could not be kept")
        self.assertEqual((self.process(), self.orchestrator()), (ran, "retired"))
        self.assertIn(f"❯ {DRAFT}", self.seat.capture())


if __name__ == "__main__":
    unittest.main()
