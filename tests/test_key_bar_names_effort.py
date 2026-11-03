"""A seat's bar names its own orchestrator effort beside its model, and follows a step on `c`.

Black-box against AK_BIN: a person's terminal reads the seat's two-line bar, as in
test_key_seat_status_bar.py; the seat's effort differs from config.toml and its workers'.
A model running at no effort shows its name alone.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

KEY = "Ctrl-b m  menu"


def bar(screen):
    return [row.rstrip() for row in screen.rstrip("\n").split("\n")[-2:]]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class BarNamesEffort(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"opus": {"effort": "high"}})
        fakeadapter.install(self.home, claude="pass")

    def terminal(self, model="opus", effort="xhigh"):
        seat = Seat(self.home, "acme-fix", model=model, record={"efforts": {
            model: {"effort": effort, "exec_effort": "medium", "review_effort": "low"}}})
        term = Terminal(self.home, "orch", seat.name, size=(100, 30))
        term.wait(seat.name)
        done = self.home.ak("orch", "why", seat.name)
        self.assertEqual(done.code, 0, done.err)
        term.wait(lambda screen: screen.rstrip().endswith(KEY))
        return seat, term

    def test_the_bar_names_the_recorded_effort_and_follows_a_step_on_c(self):
        seat, term = self.terminal()
        self.assertRegex(bar(term.screen())[0], r" +acme-fix +Opus 5\.5 xhigh$")
        settings = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                            env={"NO_COLOR": "1", "AGENTKIT_SESSION": seat.name})
        settings.wait("esc leave")
        settings.keys("c")
        settings.wait(lambda screen: "› Opus 5.5" in screen and "esc back" in screen)
        settings.keys("Right", "Space")     # xhigh -> max
        self.assertEqual(seat.wait_lines(1), ["/effort max"])
        settings.wait(lambda screen: any(line.lstrip("› ").startswith("Opus 5.5")
                                        and line.split()[5] == "max"
                                        for line in screen.split("\n")))
        settings.keys("Space")              # max -> low
        self.assertEqual(seat.wait_lines(2), ["/effort max", "/effort low"])
        screen = term.wait(lambda screen: bar(screen)[0].endswith("Opus 5.5 low"))
        self.assertRegex(bar(screen)[0], r" +acme-fix +Opus 5\.5 low$")

    def test_no_effort_shows_the_model_alone(self):
        akconfig.write(self.home, {"opus": {"effort": "none"}})
        _, term = self.terminal(effort="none")
        self.assertRegex(bar(term.screen())[0], r" +acme-fix +Opus 5\.5$")

    def test_a_model_without_effort_shows_its_name_alone(self):
        akconfig.write(self.home, {"haiku": {"harness": "claude", "model": "claude-haiku-4-5",
                                            "effort": "none"}})
        _, term = self.terminal(model="haiku", effort="none")
        self.assertRegex(bar(term.screen())[0], r" +acme-fix +Haiku 4\.5$")


if __name__ == "__main__":
    unittest.main()
