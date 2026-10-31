"""An OpenCode seat moved on `c` to another OpenCode model, at a variant OpenCode itself defines, is
typed `/ak-model <id> <effort>` in its harness's process, asking nothing; moved at `none`, a
variant only a launch defines, it asks and restarts as before, and is typed nothing.

The owner (30 Oct 2026), of a move within one harness: in place, with no restart, "for every
harness".  OpenCode reads the variants a launch defines only as it starts.  Black-box: `AK_BIN`,
as the popup over a seat on DeepSeek V4.1 Flash Free at `max` whose pane keeps each line typed
into it, its harness a fake answering `variants` as adapters/opencode.sh does; fails against
`/bin/false`."""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT, TOKEN, SESSION = "acme-fix", "d" * 32, "ses_0fa1c2d3e4ffAcmeSwitch"
DEEPSEEK, GLM = "opencode/deepseek-v4.1-flash-free", "opencode/glm-5.3-flash-free"
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpencodeSwitchesInPlace(unittest.TestCase):
    def move(self, effort):
        """The seat on DeepSeek at `max`, its mark on `c` moved to GLM-5.3-Flash Free at `effort`:
        the seat and its record's path."""
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fake = fakeadapter.install(home, opencode="pass")["opencode"]
        for model in (DEEPSEEK, GLM):
            said = home.run(REPO / "adapters/opencode.sh", "variants", model)
            self.assertEqual(said.code, 0, said.err)
            self.fake.answer("variants", said.out.strip(), given=[model])
        akconfig.write(home, {
            "deepseek": {"harness": "opencode", "model": DEEPSEEK, "provider": "opencode",
                         "effort": "max"},
            "glm": {"harness": "opencode", "model": GLM, "provider": "opencode",
                    "effort": effort}})
        home.write(f".agentkit/state/opencode-launch-{TOKEN}/session", SESSION)
        seat = Seat(home, SEAT, model="deepseek", screen="opencode-prompt-pane.txt",
                    composer="┃  Ask anything…", record={"opencode_launch": TOKEN})
        self.pid = self.pane_pid(seat)
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS
                  and "› DeepSeek V4.1 Flash Free" in screen)
        term.keys("Down", "Space")     # GLM-5.3-Flash Free's orchestrator mark
        return seat, term, home.path / ".agentkit" / "state" / f"session-{SEAT}.json"

    def pane_pid(self, seat):
        return self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_pid}").out.strip()

    def test_a_variant_opencode_defines_is_typed_into_it_asking_nothing(self):
        seat, term, path = self.move("high")
        self.assertEqual(seat.wait_lines(1), [f"/ak-model {GLM} high"])
        screen = term.wait(lambda screen: key_line(screen) == KEYS
                           and json.loads(path.read_text())["orchestrator"] == "glm")
        self.assertNotIn(f"  Restart {SEAT} on", screen)
        self.assertEqual(self.pane_pid(seat), self.pid)
        self.assertEqual(self.fake.calls("interactive"), [])

    def test_none_which_only_a_launch_defines_asks_and_restarts_it(self):
        seat, term, path = self.move("none")
        term.wait(lambda screen: f"  Restart {SEAT} on GLM-5.3-Flash Free?" in rows(screen)
                  and "  ✗ Move" in rows(screen))
        term.keys("Down", "Enter")
        term.wait(lambda _: self.pane_pid(seat) != self.pid)
        self.assertEqual(json.loads(path.read_text())["orchestrator"], "glm")
        [launched] = self.fake.calls("interactive")
        self.assertEqual(launched["argv"][:3], [GLM, "none", SESSION])
        self.assertEqual(seat.lines(), [])


if __name__ == "__main__":
    unittest.main()
