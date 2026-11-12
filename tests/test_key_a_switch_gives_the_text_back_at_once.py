"""A switch gives the owner's unsent text back in the new harness's input field as soon as that
harness shows one empty, with no tick, though the popup it was made from closes at once.

The owner (12 Nov 2026): "Swithich providers, models, accounts, always the input in the text
field must be preserved."  Black-box: `AK_BIN`, as the popup over a seat, moves it on `c` to
GPT-6-Astra and, once text stands in that harness's input field, back to Opus 5.5, harnesses of
two kinds, each a restart; no `ak watch` runs.  Each harness ak launches is a fake whose Ctrl-G
hands its input field to $VISUAL, as Claude Code's and Codex's do (tests/fixtures/akpane.py).
"""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import FIXTURES, PANE, Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
DRAFT = "and add these posts"
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
STARTING = "Claude Code is starting\n\n\n"     # no input field drawn yet


def key_line(screen):
    return next((line for line in reversed(screen.rstrip("\n").split("\n")) if line), "")


def until(test, what, bound=30):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never: {what}")
        time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASwitchGivesTheTextBackAtOnce(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, ["opus", "astra"], workers=["opus"])
        self.seat = Seat(home, SEAT, model="opus")
        self.screens = {}
        for harness, composer, screen in (("codex", "›", "codex-prompt-pane.txt"),
                                          ("claude", "❯", STARTING)):
            shown = self.screens[harness] = home.root / "panes" / f"{harness}.txt"
            shown.write_text(screen if "\n" in screen else (FIXTURES / screen).read_text())
            fakes[harness].answer("interactive", shlex.join(
                [sys.executable, str(PANE), "--editor", str(shown),
                 str(shown.with_suffix(".typed")), composer]))
        fakes["codex"].answer("interactive", "", 3, given=["new"])  # Codex takes no id of ours
        self.term = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)

    def orchestrator(self):
        path = self.home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        return json.loads(path.read_text())["orchestrator"]

    def restart(self, *keys, on):
        """The seat moved by those keys on the `c` screen, its restart confirmed."""
        self.term.keys(*keys, "Space")
        self.term.wait(lambda screen: f"  Restart {SEAT} on {on}?" in screen)
        self.term.keys("Down", "Enter")
        self.term.wait(lambda screen: key_line(screen) == KEYS and on in screen)

    def shows(self, text):
        return text in self.home.tmux("capture-pane", "-p", "-t", self.seat.pane).out

    def test_the_text_is_back_once_the_new_harness_shows_its_input_field(self):
        self.restart("Down", on="GPT-6-Astra")
        until(lambda: self.orchestrator() == "astra" and self.shows("› Ask Codex"),
              "the seat on Codex, its input field empty")
        self.home.tmux("send-keys", "-t", self.seat.pane, "-l", DRAFT)    # the owner's
        until(lambda: self.shows(f"› {DRAFT}"), "the owner's text in Codex's input field")
        self.restart("Up", on="Opus 5.5")
        self.term.keys("Escape", "Escape")      # the popup closes at once
        self.assertEqual(self.term.exit_code(), 0)
        until(lambda: self.orchestrator() == "opus" and self.shows("Claude Code is starting"),
              "the seat on Claude Code, which draws no input field yet")
        self.assertFalse(self.shows(DRAFT))
        self.screens["claude"].write_text((FIXTURES / "claude-prompt-pane.txt").read_text())
        until(lambda: self.shows(f"❯ {DRAFT}"), "the text back in Claude Code's input field")


if __name__ == "__main__":
    unittest.main()
