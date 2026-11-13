"""A move on `c` within the seat's provider that its harness takes in place (orch.switch_lines)
types its lines into the running harness without running that adapter's `auth`, even where `auth`
would answer no; a move that restarts the seat or moves to another provider's model asks `auth`
first, and refuses with its answer, leaving the seat as it was.

Black-box: `AK_BIN`, as the popup over a seat whose pane keeps each line typed into it, its
harnesses fakes; fails against `/bin/false`."""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"
NO_LOGIN = "token expired; run login"
METER = '{"meters": [{"name": "weekly_all", "used": 10}]}'
DEEPSEEK, ACME_GLM = "opencode/deepseek-v4.1-flash-free", "acme/glm-5.3-flash"
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def rows(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(rows(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AMoveInPlaceAsksNoLogin(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fakes = fakeadapter.install(home, claude="pass", codex="pass")
        for fake in self.fakes.values():
            fake.answer("usage", METER)
        self.fakes["claude"].answer("auth", NO_LOGIN, 1)
        akconfig.write(home, ["opus", "fable", "astra"], workers=["opus"])
        self.seat = Seat(home, SEAT, model="opus",
                         record={"reviewers": ["astra"], "efforts": {"opus": {"effort": "xhigh"}}})
        self.path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        self.term = self.open_c("› Opus 5.5")

    def open_c(self, needle):
        term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS and needle in screen)
        return term

    def pid(self, seat=None):
        return self.home.tmux("display-message", "-p", "-t", (seat or self.seat).pane,
                              "#{pane_pid}").out.strip()

    def record(self):
        return json.loads(self.path.read_text())

    def test_another_model_of_its_harness_and_login_runs_no_auth(self):
        pid = self.pid()
        self.term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        self.assertEqual(self.seat.wait_lines(2),
                         ["/model claude-fable-5-1", "/effort xhigh"])
        screen = self.term.wait(lambda screen: key_line(screen) == KEYS
                                and self.record()["orchestrator"] == "fable")
        self.assertNotIn(f"  Restart {SEAT} on Fable 5.1?", rows(screen))
        self.assertEqual(self.pid(), pid)
        self.assertEqual(self.fakes["claude"].calls("auth"), [])
        self.assertEqual(self.fakes["claude"].calls("interactive"), [])

    def test_an_effort_step_on_its_own_model_runs_no_auth(self):
        pid = self.pid()
        self.term.keys("Right", "Space")    # Opus 5.5's orchestrator effort
        self.assertEqual(self.seat.wait_lines(1), ["/effort max"])
        self.term.wait(lambda screen: any(line.lstrip("› ").startswith("Opus 5.5")
                                          and line.split()[5] == "max" for line in rows(screen)))
        self.assertEqual(self.record()["efforts"]["opus"]["effort"], "max")
        self.assertEqual(self.pid(), pid)
        self.assertEqual(self.fakes["claude"].calls("auth"), [])
        self.assertEqual(self.fakes["claude"].calls("interactive"), [])

    def test_a_move_whose_pane_is_gone_is_refused_by_auth_and_left_as_it_was(self):
        self.home.tmux("new-window", "-d", "-t", f"={SEAT}:", "sleep 86400")
        self.home.tmux("kill-pane", "-t", self.seat.pane)
        before = self.path.read_bytes()
        self.term.keys("Down", "Space")     # Fable 5.1's orchestrator mark
        screen = self.term.wait(lambda screen: f"  fable: {NO_LOGIN}" in rows(screen))
        self.assertNotIn(f"  Restart {SEAT} on Fable 5.1?", rows(screen))
        self.term.keys("Up", "Right", "Space")   # Opus 5.5's orchestrator effort
        screen = self.term.wait(lambda screen: f"  opus: {NO_LOGIN}" in rows(screen))
        self.assertNotIn(f"  Restart {SEAT} on Opus 5.5 at max?", rows(screen))
        self.assertEqual([call["argv"] for call in self.fakes["claude"].calls("auth")],
                         [["seat"], ["seat"]])
        self.assertEqual(self.fakes["claude"].calls("interactive"), [])
        self.assertEqual(self.path.read_bytes(), before)

    def test_another_provider_s_model_in_the_same_harness_asks_auth_first(self):
        token = "d" * 32
        fake = fakeadapter.install(self.home, opencode="pass")["opencode"]
        fake.answer("usage", '{"meters": []}')
        fake.answer("auth", f"opencode: {NO_LOGIN}", 1)
        fake.answer("models", f"{ACME_GLM}\tAcme GLM\tlow,high,max")
        for model in (DEEPSEEK, ACME_GLM):
            said = self.home.run(REPO / "adapters/opencode.sh", "variants", model)
            self.assertEqual(said.code, 0, said.err)
            fake.answer("variants", said.out.strip(), given=[model])
        akconfig.write(self.home, {
            "deepseek": {"harness": "opencode", "model": DEEPSEEK, "provider": "opencode",
                         "effort": "max"},
            "glm": {"harness": "opencode", "model": ACME_GLM, "provider": "acme",
                    "effort": "high"}})
        self.home.tmux("kill-session", "-t", f"={SEAT}")
        self.home.write(f".agentkit/state/opencode-launch-{token}/session", "ses_0fa1c2d3e4ffAcme")
        seat = Seat(self.home, SEAT, model="deepseek", screen="opencode-prompt-pane.txt",
                    composer="┃  Ask anything…", record={"opencode_launch": token})
        term = self.open_c("› DeepSeek V4.1 Flash Free")
        pid, before = self.pid(seat), self.path.read_bytes()
        term.keys("Down", "Space")          # Acme GLM's orchestrator mark, on provider `acme`
        term.wait(lambda screen: f"  glm: opencode: {NO_LOGIN}" in rows(screen))
        self.assertEqual([call["argv"] for call in fake.calls("auth")], [["seat"]])
        self.assertEqual(seat.lines(), [])
        self.assertEqual(self.pid(seat), pid)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
