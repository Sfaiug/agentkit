"""A seat's `c` opens, and `a` applies, on the usage readings ak holds: neither asks an adapter
for usage, nor waits for one being asked.

The owner (12 Nov 2026): "Switching takes too long … Does not react."  `c` waited on every
login's usage before it drew, and `a` before it moved a seat, up to 30 s an adapter.  Black-box:
`AK_BIN` in a person's terminal over a seat whose pane keeps each line typed into it, its
harnesses fakes whose `usage` writes down that it ran and then sleeps past every wait here, no
reading held.  The menu's own probe asks one of them and stays asleep in it; `c` draws the
seat's rows and `a` moves it with no `usage` run since.  Fails on origin/main, where both wait
behind that probe, one adapter after another; and against `/bin/false`.
"""

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
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CWaitsForNoUsageProbe(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.asked = self.home.root / "usage-asked"
        for fake in fakeadapter.install(self.home, claude="pass", codex="pass").values():
            shebang, rest = fake.script.read_text().split("\n", 1)
            fake.script.write_text(f'{shebang}\n[ "$1" = usage ] && {{ echo {fake.harness} >>'
                                   f'{shlex.quote(str(self.asked))}; exec sleep 600; }}\n{rest}')
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "opus": "claude", "astra": "codex"},
                       workers=["fable"], reviewers=["astra"])
        self.seat = Seat(self.home, SEAT, model="opus", record={"reviewers": ["astra"]})

    def terminal(self, *argv, **env):
        term = Terminal(self.home, *argv, size=(100, 30), env={"NO_COLOR": "1", **OFFLINE, **env})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        return term

    def usage_runs(self):
        try:
            return self.asked.read_text().split()
        except FileNotFoundError:
            return []

    def probed(self):
        """The `usage` runs once the menu's own probe is asleep in one."""
        deadline = time.monotonic() + 30
        while not self.usage_runs():
            self.assertLess(time.monotonic(), deadline, "the menu's probe never asked for usage")
            time.sleep(0.05)
        return self.usage_runs()

    def test_a_seat_s_c_draws_its_rows(self):
        term = self.terminal("attach", "--overlay", AGENTKIT_SESSION=SEAT)
        term.wait("esc leave")
        before = self.probed()
        term.keys("c")
        screen = term.wait(lambda screen: key_line(screen) == KEYS)
        self.assertTrue(any(line.lstrip("› ").startswith("Opus 5.5") for line in rows(screen)),
                        screen)
        self.assertEqual(self.usage_runs(), before)

    def test_a_moves_a_seat(self):
        term = self.terminal()
        term.wait("c config")
        before = self.probed()
        term.keys("c")
        term.wait(lambda screen: "a apply to all sessions" in key_line(screen))
        term.keys("a")
        term.wait(lambda screen: "  × Apply" in rows(screen))
        term.keys("Down", "Enter")
        self.assertEqual(self.seat.wait_lines(2), ["/model claude-fable-5-1", "/effort xhigh"])
        self.assertEqual(self.usage_runs(), before)


if __name__ == "__main__":
    unittest.main()
