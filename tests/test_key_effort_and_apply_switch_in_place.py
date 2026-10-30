"""An effort step on a running Claude seat, and `a apply to all sessions`, switch in place what can.

The owner (30 Oct 2026): "if it is merely a model change or effort, or both, then the change
should be able to happen inside the session, without any need to restart."  A step on a seat's
`c` types only `/effort <level>` into its harness's process, asks nothing, and its record holds the
level.  `a`, over a seat that can switch in place and one that must restart, names only the
second on its card and moves both.  Black-box: `AK_BIN`, in a person's terminal, over seats whose
panes keep each line typed into them, their harnesses fakes; fails against `/bin/false`.
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

OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SwitchInPlace(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")

    def terminal(self, *argv, **env):
        term = Terminal(self.home, *argv, size=(100, 30), env={"NO_COLOR": "1", **OFFLINE, **env})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        return term

    def record(self, name):
        return json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())

    def on_fable(self, name):
        record = self.record(name)
        return (record["orchestrator"], (record.get("efforts") or {}).get("fable", {}).get(
            "effort")) == ("fable", "xhigh")

    def pid(self, seat):
        return self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_pid}").out.strip()

    def test_an_effort_step_goes_into_the_same_process_asking_nothing(self):
        akconfig.write(self.home, ["opus", "astra"], workers=["opus"])
        seat = Seat(self.home, "acme-fix", model="opus", record={
            "reviewers": ["astra"], "efforts": {"opus": {"effort": "xhigh"}}})
        pid = self.pid(seat)
        term = self.terminal("attach", "--overlay", AGENTKIT_SESSION="acme-fix")
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "› Opus 5.5" in screen and "␣ mark" in key_line(screen))
        term.keys("Right", "Space")     # its effort, one step up from xhigh
        self.assertEqual(seat.wait_lines(1), ["/effort max"])
        screen = term.wait(lambda screen: any(
            line.lstrip("› ").startswith("Opus 5.5") and line.split()[5] == "max"
            for line in rows(screen)))
        self.assertNotIn("  Restart acme-fix on Opus 5.5 at max?", rows(screen))
        self.assertNotIn("  ✗ Restart", rows(screen))
        self.assertEqual(self.record("acme-fix")["efforts"]["opus"]["effort"], "max")
        self.assertEqual(self.pid(seat), pid)
        self.assertEqual(self.fakes["claude"].calls("interactive"), [])

    def test_a_names_only_the_seat_that_restarts_and_moves_both(self):
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "opus": "claude", "astra": "codex"},
                       workers=["fable"], reviewers=["astra"])
        here = Seat(self.home, "acme-here", model="opus", record={"reviewers": ["astra"]})
        away = Seat(self.home, "acme-away", model="astra", screen="codex-prompt-pane.txt",
                    record={"workers": ["astra"], "reviewers": ["astra"]})
        pids = self.pid(here), self.pid(away)
        term = self.terminal()
        term.wait("c config")
        term.keys("c")
        term.wait(lambda screen: "a apply to all sessions" in key_line(screen))
        term.keys("a")
        screen = term.wait(lambda screen: "  ✗ Apply" in rows(screen))
        self.assertIn("  acme-away restarts on Fable 5.1 at xhigh.", rows(screen))
        term.keys("Down", "Enter")
        self.assertEqual(here.wait_lines(2), ["/model claude-fable-5-1", "/effort xhigh"])
        deadline = time.monotonic() + 30
        while self.pid(away) == pids[1] or not all(
                self.on_fable(name) for name in ("acme-here", "acme-away")):
            self.assertLess(time.monotonic(), deadline, "a seat never moved to fable at xhigh")
            time.sleep(0.1)
        self.assertEqual(self.pid(here), pids[0])
        [launched] = self.fakes["claude"].calls("interactive")
        self.assertEqual((launched["env"]["AGENTKIT_SESSION"], *launched["argv"][:2]),
                         ("acme-away", "claude-fable-5-1", "xhigh"))


if __name__ == "__main__":
    unittest.main()
