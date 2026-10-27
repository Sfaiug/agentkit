"""On a seat's `c`, a build effort step changes that seat's own efforts, in its record, and
nothing else: no other seat's record and not config.toml, whose entries are what new seats take.

The owner (24 Oct 2026): inside a session, `c` edits only that session.  Black-box: the program
`AK_BIN` names, as the popup over one of two seats on one model at the same efforts
(tests/fixtures/akseat.py), in a person's terminal (tests/fixtures/akterm.py), its harnesses
the fakes of tests/fixtures/fakeadapter.py, judged by what the terminal shows, the seats'
records and config.toml; this test fails against `/bin/false`.
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

SEATS = ("acme-fix", "acme-ask")
EFFORTS = {"opus": {"effort": "xhigh"}, "astra": {"effort": "xhigh"}}
KEYS = "  ↑↓←→ move   ⏎ choose   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def opus_efforts(screen):
    """The efforts Opus 5.5's row shows beside its orchestrator and builds marks, each after
    that mark's bar."""
    return next(line.split()[5:9:3] for line in lines(screen)
                if line.lstrip("› ").startswith("Opus 5.5"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatEfforts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        cls.seats = {name: Seat(home, name, model="opus",
                                record={"reviewers": ["astra"], "efforts": EFFORTS})
                     for name in SEATS}
        cls.config = home.path / ".agentkit" / "config.toml"

    def setUp(self):
        # each case starts from the config and the records as the seats were opened with them
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"])
        for name, seat in self.seats.items():
            self.home.write(f".agentkit/state/session-{name}.json", seat.record)
        self.given = self.config.read_bytes()

    def c(self, seat):
        """`c` in the popup over `seat`, Opus 5.5's row highlighted."""
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": seat, **OFFLINE})
        # ends this case's menu, keeping the terminal's server for the next case
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        screen = term.wait(lambda screen: key_line(screen) == KEYS and "› Opus 5.5" in screen)
        self.assertIn(f"  For  {seat}", lines(screen))
        return term, screen

    def record(self, name):
        return json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())

    def until(self, test, what):
        deadline = time.monotonic() + 30
        while not test():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def others_kept(self):
        self.assertEqual(self.config.read_bytes(), self.given)
        self.assertEqual(self.record("acme-ask")["efforts"], EFFORTS)

    def test_a_step_on_a_seat_s_c_is_that_seat_s_alone(self):
        term, screen = self.c("acme-fix")
        self.assertEqual(opus_efforts(screen), ["xhigh", "xhigh"])
        term.keys("Right", "Right", "Right", "Enter")      # onto the build effort, and a step
        # the orchestrator's effort beside it stays where it was
        term.wait(lambda screen: opus_efforts(screen) == ["xhigh", "max"])
        self.until(lambda: self.record("acme-fix")["efforts"]["opus"] == {
            "effort": "xhigh", "exec_effort": "max"},
                   "acme-fix's record never took the step")
        self.assertEqual(self.record("acme-fix")["efforts"]["astra"], EFFORTS["astra"])
        self.others_kept()
        self.assertEqual(opus_efforts(self.c("acme-ask")[1]), ["xhigh", "xhigh"])


if __name__ == "__main__":
    unittest.main()
