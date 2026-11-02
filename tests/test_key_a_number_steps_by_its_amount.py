"""←/→ on a number of `c` move it by an amount fit for it: `rounds` 1, `review_lines` 50,
`seat_lines` 10, no further than its floor.

On 2 November 2026 the rows stepped by one, so taking `review_lines` from 300 to 1000 took 700
presses.  Black-box, as tests/test_key_policy_on_the_c_screen.py: the program `AK_BIN` names, in
a person's terminal (tests/fixtures/akterm.py), judged by the screen and config.toml.  This test
fails against `/bin/false`.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}
FAR = {"rounds": 6, "review_lines": 7, "seat_lines": 8}     # j presses from the first model


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class StepsByItsAmount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")

    def stepped(self, name, key, shows, settings=None):
        """`key` on `name`'s row of a `c` over `settings` shows `shows`, saved."""
        akconfig.write(self.home, MODELS, settings=settings)
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys(*["j"] * FAR[name])
        term.wait(f"› {name}")
        term.keys(key)
        said = next(line for line in term.wait("saved").split("\n") if line.startswith("› "))
        self.assertEqual(said.split()[1:3], [name, str(shows)])
        self.assertEqual(akconfig.read(self.home)[name], shows)

    def test_review_lines_steps_by_fifty(self):
        self.stepped("review_lines", "Right", 350)

    def test_seat_lines_steps_by_ten(self):
        self.stepped("seat_lines", "Left", 40)

    def test_a_step_past_the_floor_lands_on_it(self):
        self.stepped("seat_lines", "Left", 0, {"seat_lines": 5})

    def test_rounds_steps_by_one(self):
        self.stepped("rounds", "Right", 4)


if __name__ == "__main__":
    unittest.main()
