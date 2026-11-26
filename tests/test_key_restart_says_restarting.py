"""Picking `Restart` on the card that asks before a seat's orchestrator moves puts `restarting` in
the header while the switch runs, every line under it as it was and nothing moving; once the
switch is done the header is the page's again and the seat is on the other model; `Keep` never
says `restarting`.

The owner (24 Nov 2026): no wait is silent.  Black-box: the program `AK_BIN` names, as the popup
over a seat on Opus 5.5 (tests/fixtures/akseat.py), in a person's true-colour terminal
(tests/fixtures/akterm.py) with its motion clock held (`AK_MOTION_CLOCK`), its harnesses the
fakes of tests/fixtures/fakeadapter.py.  The switch is held on the seat's record's lock, taken
and let go once ak waits on it, as tests/test_key_the_header_says_a_session_is_starting.py holds
a seat's making.  Fails against `/bin/false`.
"""

import fcntl
import json
from pathlib import Path
import re
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_a_job_keeps_a_run_changed_while_it_adopts_it import waited_on

SEAT = "acme-fix"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def lines(screen):
    return [line.rstrip() for line in screen.rstrip("\n").split("\n")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RestartSaysRestarting(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        # as Codex's adapter does: its TUI takes no conversation id of ak's making
        fakes["codex"].answer("interactive", "", 3, given=["new"])
        akconfig.write(home, ["opus", "astra"], workers=["opus"])
        Seat(home, SEAT, model="opus", record={"reviewers": ["astra"]})
        self.state = home.path / ".agentkit/state"
        self.record = self.state / f"session-{SEAT}.json"
        self.clock = home.write("clock", "1000")
        self.term = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(self.clock),
                                  "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "› Opus 5.5" in screen and "␣ mark" in screen)

    def asked(self):
        """Space on 6 Astra's orchestrator mark: the card up with Keep highlighted."""
        self.term.keys("Down")
        self.term.wait(lambda screen: any(line.startswith("› 6 Astra") for line in lines(screen)))
        self.term.keys("Space")
        self.term.wait(lambda screen: f"  Restart {SEAT} on 6 Astra?" in lines(screen)
                       and "› ✓ Keep" in lines(screen) and "  × Restart" in lines(screen))

    def test_restart_names_itself_in_the_header_while_the_switch_runs(self):
        self.asked()
        self.term.keys("Down")
        self.term.wait(lambda screen: "› × Restart" in lines(screen)
                       and "⏎ restart" in lines(screen)[-1])
        # let the highlight move from Keep onto Restart finish so `before` is at rest
        self.clock.write_text("1001")
        self.term.wait(lambda _: not any(
            "✓ Keep" in line and "\x1b[48;" in line
            for line in self.term.screen(colours=True).rstrip("\n").split("\n")))
        before = self.term.screen(colours=True).rstrip("\n").split("\n")
        lock = self.state / f".session-{SEAT}.lock"
        with lock.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.term.keys("Enter")
            deadline = time.monotonic() + 30
            while not waited_on(lock):
                self.assertLess(time.monotonic(), deadline,
                                f"ak never started the switch; it shows:\n{self.term.screen()}")
                time.sleep(0.05)
            shown = self.term.wait(
                lambda screen: lines(screen)[0].startswith("agentkit · config · restarting "))
            self.assertRegex(lines(shown)[0], r"^agentkit · config · restarting +\d\d:\d\d$")
            during = self.term.screen(colours=True).rstrip("\n").split("\n")
            self.assertEqual(during[1:], before[1:])
            # moving the motion clock on while the switch runs changes no cell
            for step in range(1, 6):
                self.clock.write_text(str(1001 + step * 0.05))
                time.sleep(0.05)
            self.assertEqual(self.term.screen(colours=True).rstrip("\n").split("\n"), during)
        after = self.term.wait(lambda screen: "␣ mark" in lines(screen)[-1]
                               and not lines(screen)[0].startswith("agentkit · config · restarting"))
        self.assertRegex(lines(after)[0], r"^agentkit · config +\d\d:\d\d$")
        self.assertEqual(json.loads(self.record.read_text())["orchestrator"], "astra")

    def test_keep_never_says_restarting(self):
        self.asked()
        stream = self.home.root / "keep-stream"
        self.term._ask("pipe-pane", "-O", "-t", self.term.pane,
                       f"cat > {shlex.quote(str(stream))}")
        deadline = time.monotonic() + 10
        while not stream.exists():
            self.assertLess(time.monotonic(), deadline, "tmux did not open pipe-pane")
            time.sleep(0.05)
        self.term.keys("Enter")
        after = self.term.wait(lambda screen: "␣ mark" in lines(screen)[-1]
                               and "✓ Keep" not in screen)
        self.assertRegex(lines(after)[0], r"^agentkit · config +\d\d:\d\d$")
        self.term._ask("pipe-pane", "-t", self.term.pane)
        self.assertNotIn(b"restarting", stream.read_bytes())
        self.assertEqual(json.loads(self.record.read_text())["orchestrator"], "opus")


if __name__ == "__main__":
    unittest.main()
