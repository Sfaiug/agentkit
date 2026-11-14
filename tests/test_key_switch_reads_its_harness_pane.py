"""A seat moved on `c` is read, kept and restarted at its harness's own pane, whichever window
of its session the owner has selected: an empty field in another window lets no restart take the
text left unsent in the harness's.  With no harness pane recorded, as older launches left a seat,
that pane is the one selected as the move is made, whichever the owner selects after.

ak read the selected window's empty field as the seat's and respawned the harness's pane, losing
its text; with none recorded, it read one window and respawned whichever was selected by then.
Black-box: `AK_BIN`, as the popup over a seat whose record names a model the config no longer
has, its pane tests/fixtures/akpane.py running as `claude`, and a second window, the same program.
Judged by each pane's process, what it shows and the seat's record."""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, SOCKET, Home
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
        self.fake = fakeadapter.install(self.home, claude="pass")["claude"]
        akconfig.write(self.home, ["opus", "fable"], workers=["opus"])
        self.seat = Seat(self.home, SEAT, record={"orchestrator": "retired"}, program="claude")

    def wait(self, pane, text):
        deadline = time.monotonic() + 30
        while text not in self.home.tmux("capture-pane", "-p", "-t", pane).out:
            self.assertLess(time.monotonic(), deadline, self.seat.capture())
            time.sleep(0.05)

    def process(self, pane=None):
        return self.home.tmux("display-message", "-p", "-t", pane or self.seat.pane,
                              "#{pane_pid}").out

    def orchestrator(self):
        path = self.home.path / f".agentkit/state/session-{SEAT}.json"
        return json.loads(path.read_text())["orchestrator"]

    def window(self, *flags):
        """A second window of the seat's session, the same program showing an empty field."""
        panes = self.home.root / "panes"
        (panes / "other.txt").write_text((FIXTURES / "claude-prompt-pane.txt").read_text())
        other = self.home.tmux("new-window", *flags, "-t", f"={SEAT}:", "-P", "-F", "#{pane_id}",
                               shlex.join([sys.executable, str(self.seat.program),
                                           str(panes / "other.txt"), str(panes / "other.typed"),
                                           "❯"])).out.strip()
        self.wait(other, "❯")
        return other

    def asked(self):
        """The popup's card asking to restart the seat on Opus 5.5."""
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        term.keys("Space")             # Opus 5.5's orchestrator mark
        term.wait(f"Restart {SEAT} on Opus 5.5?")
        return term

    def test_an_empty_field_in_the_selected_window_restarts_no_harness_holding_text(self):
        self.home.tmux("send-keys", "-t", self.seat.pane, "-l", DRAFT)
        self.wait(self.seat.pane, f"❯ {DRAFT}")
        self.window()
        ran = self.process()
        term = self.asked()
        term.keys("Down", "Enter")     # Move
        term.wait(f"{SEAT} stays on retired: the text in its input field could not be kept")
        self.assertEqual((self.process(), self.orchestrator()), (ran, "retired"))
        self.assertIn(f"❯ {DRAFT}", self.seat.capture())

    def test_with_no_pane_recorded_another_window_selected_as_it_moves_keeps_its_text(self):
        self.home.tmux("set-option", "-u", "-t", f"={SEAT}:", "@ak_harness_pane")
        other = self.window("-d")
        self.home.tmux("send-keys", "-t", other, "-l", DRAFT)
        self.wait(other, f"❯ {DRAFT}")
        # The owner selects that window once, as the harness's command is asked for: after the
        # move has read the seat's field, before it restarts the seat's harness.
        armed = self.home.root / "armed"
        self.fake.script.write_text(self.fake.script.read_text().replace("exec ", (
            f'[ "$1" = interactive ] && rm {shlex.quote(str(armed))} 2>/dev/null && '
            f"tmux -L {SOCKET} select-window -t {other}\nexec "), 1))
        ran, kept = self.process(), self.process(other)
        term = self.asked()
        armed.touch()
        term.keys("Down", "Enter")     # Move
        # the record names the model before the harness is restarted: its process says it was
        term.wait(lambda screen: "stays on retired" in screen or self.process() != ran)
        self.assertFalse(armed.exists(), "the harness's command was never asked for")
        self.assertNotEqual(self.process(), ran, term.screen())
        self.assertEqual((self.orchestrator(), self.process(other)), ("opus", kept))
        self.assertIn(f"❯ {DRAFT}", self.home.tmux("capture-pane", "-p", "-t", other).out)


if __name__ == "__main__":
    unittest.main()
