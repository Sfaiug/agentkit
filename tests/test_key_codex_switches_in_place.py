"""A Codex seat moved on `c` to another Codex model of its login is typed `/model <id>
--reasoning=<level>` in its harness's process, asking nothing, and runs on.

The owner (30 Oct 2026), of a move within one harness: in place, with no restart, "for every
harness".  Black-box: `AK_BIN`, as the popup over a seat on GPT-6-Astra whose pane keeps each
line typed into it, its harness a fake; fails against `/bin/false`."""

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
class CodexSwitchesInPlace(unittest.TestCase):
    def test_another_codex_model_of_its_login_is_typed_into_it_asking_nothing(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, codex="pass")
        akconfig.write(home, {"astra": {}, "luna": {"harness": "codex", "model": "gpt-5.6-luna"}})
        seat = Seat(home, SEAT, model="astra", screen="codex-prompt-pane.txt", composer="›")
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and "› GPT-6-Astra" in screen)
        pid = home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_pid}").out
        path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        term.keys("Down", "Space")     # the other Codex model's orchestrator mark
        self.assertEqual(seat.wait_lines(1), ["/model gpt-5.6-luna --reasoning=high"])
        screen = term.wait(lambda screen: key_line(screen) == KEYS
                           and json.loads(path.read_text())["orchestrator"] == "luna")
        self.assertNotIn(f"  Restart {SEAT} on", screen)
        self.assertEqual(home.tmux("display-message", "-p", "-t", seat.pane,
                                   "#{pane_pid}").out, pid)
        self.assertEqual(fakes["codex"].calls("interactive"), [])


if __name__ == "__main__":
    unittest.main()
