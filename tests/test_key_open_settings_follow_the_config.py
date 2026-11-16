"""An open `c` reads config.toml again when another process changes it, no key pressed: a model
picked inside a seat that no entry runs, added to the config by whoever looks at the seat first,
has its row on a `c` already open, the seat's orchestrator mark on it where `c` is over that
seat, and the highlight stays on its row.  The owner: "The model and effort in the harness
setting, and in ak should be as linked and live as possible."

Black-box against AK_BIN, as the popup over the seat or over none; the model is added as
test_key_model_added_where_no_entry_runs_it adds it: the launch's status command, run as Claude
Code runs it, records an answer on a model the config runs no entry of, and `ak orch why` in
another process looks at the seat.
"""

import json
import re
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

SEAT = "acme-fix"
SONNET = "claude-sonnet-5-5"      # the shipped table names it; the config here runs no entry of it


def row(screen, label):
    """The model's row on `c`, its highlight's `›` or none taken off, or None where none is."""
    return next((line[2:] for line in screen.splitlines() if line[2:].startswith(label)), None)


def orchestrates(screen, label):
    """Whether that model's row is on the screen with its orchestrator mark, the row's first,
    filled."""
    line = row(screen, label)
    return bool(line) and re.search(r"[●○]", line).group() == "●"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpenSettingsFollowTheConfig(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "fable"], workers=["opus"])
        self.seat = Seat(home, SEAT, alive=False, record={"launched": time.time() - 600})
        done = home.ak("orch", SEAT, "--dry-run", cwd=home.path)
        self.assertEqual(done.code, 0, done.err)
        words = shlex.split(done.out.splitlines()[-1])
        self.settings = json.loads(words[words.index("--settings") + 1])
        self.seat.start()

    def open(self, env):
        """`c` open in the popup, its highlight on Opus's orchestrator mark."""
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", **env})
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "› Opus 5.5" in screen and "esc back" in screen)
        return term

    def add_sonnet(self):
        """Sonnet answered in the seat and the seat looked at by another process, once
        config.toml and the seat's record hold it."""
        socket = self.home.tmux("display-message", "-p", "-t", self.seat.pane,
                                "#{socket_path}").out.strip()
        done = self.home.run("sh", "-c", self.settings["statusLine"]["command"],
                             cwd=self.seat.cwd, env={
                                 "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "",
                                 "TMUX": socket + ",0,0", "TMUX_PANE": self.seat.pane},
                             input=json.dumps({"session_id": self.seat.record["conversation"],
                                               "model": {"id": SONNET},
                                               "effort": {"level": "low"}}))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.home.ak("orch", "why", SEAT).code, 0)
        record = self.home.path / f".agentkit/state/session-{SEAT}.json"
        deadline = time.monotonic() + 30
        while True:
            added = [name for name, entry in akconfig.read(self.home)["models"].items()
                     if entry["model"] == SONNET]
            if added and json.loads(record.read_text())["orchestrator"] == added[0]:
                return
            self.assertLess(time.monotonic(), deadline, akconfig.read(self.home)["models"])
            time.sleep(0.05)

    def leave(self, term):
        term.keys("Escape")
        term.wait("esc leave")
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)

    def test_over_the_seat_the_added_model_has_its_row_and_the_orchestrator_mark(self):
        term = self.open({"AGENTKIT_SESSION": SEAT})
        self.assertTrue(orchestrates(term.screen(), "Opus 5.5"))
        self.add_sonnet()
        term.wait(lambda screen: orchestrates(screen, "Sonnet 5.5")
                  and not orchestrates(screen, "Opus 5.5") and "› Opus 5.5" in screen)
        self.leave(term)

    def test_over_no_seat_the_added_entry_has_its_row(self):
        term = self.open({})
        self.assertIsNone(row(term.screen(), "Sonnet 5.5"))
        self.add_sonnet()
        term.wait(lambda screen: row(screen, "Sonnet 5.5") is not None
                  and "› Opus 5.5" in screen)
        self.leave(term)


if __name__ == "__main__":
    unittest.main()
