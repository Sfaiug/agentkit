"""`r your runs` on `c` opens `config · your runs · <seat>` (or `· new seats`): the lines
`ak models` prints for that seat's team now, at the screen's width, folding as the command's
fold.  Where they are taller than the screen, ↑ ↓, k j and the wheel move them a line and the
key line names `↑↓`; it always names `p models` and `esc back`.  `p` opens the company list as
it did; Esc goes back to `c`.  It reads the history and asks no board: with no board held and
none answering it opens the same.

Black-box: the program `AK_BIN` names in a terminal (tests/fixtures/akterm.py), over the team
and history of tests/test_key_models_own_tables.py, with a dead proxy for the boards; judged by
the screen and by the boards' and matrix's files left unwritten.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX
from fixtures.akboards import ENV, boards, lines
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_models_own_tables import FOLDED, OWN, TEAMS, home_of

KEYS = "  p models   esc back"
SCROLL_KEYS = "  ↑↓ scroll   p models   esc back"
WHEEL_DOWN = "\x1b[<65;5;5M"
WHEEL_UP = "\x1b[<64;5;5M"


def body_lines(shown):
    """The body lines between the rule (line 1) and the blank line above the key line."""
    last = max(i for i, line in enumerate(shown) if line)
    return shown[2:last - 1]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class YourRunsScreen(unittest.TestCase):
    def setUp(self):
        self.home = home_of(TEAMS)
        self.addCleanup(self.home.close)

    def open_c(self, size=(100, 30), seat=None):
        argv = ("attach", "--overlay") if seat else ()
        env = {**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})}
        term = Terminal(self.home, *argv, size=size, env=env)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        shown = lines(term.wait("r your runs"))
        return term, shown

    def test_r_shows_the_team_line_and_the_three_tables_headings(self):
        term, _ = self.open_c(size=(100, 30))
        term.keys("r")
        shown = lines(term.wait(lambda s: "p models" in s and "REVIEWER" in s))
        self.assertTrue(shown[0].startswith("agentkit · config · your runs · new seats"), shown[0])
        self.assertEqual(body_lines(shown), OWN)
        self.assertEqual(next(line for line in reversed(shown) if line), KEYS)
        term.keys("Escape")
        term.wait("r your runs")

        # Over a seat, a click on `r your runs` opens that seat's page and folds at 40 cells
        Seat(self.home, "acme-fix", model="nova",
             record={"orchestrator": "nova", "workers": ["bolt"], "reviewers": ["crux"]})
        seat_term, c_shown = self.open_c(size=(40, 40), seat="acme-fix")
        row = next(i for i, line in enumerate(c_shown) if "r your runs" in line)
        col = c_shown[row].index("r your runs") + 1
        seat_term.type(f"\x1b[<0;{col};{row + 1}M\x1b[<0;{col};{row + 1}m")
        folded = lines(seat_term.wait(lambda s: "p models" in s and "week on its plan" in s))
        self.assertTrue(folded[0].startswith("agentkit · your runs · acme-fix"), folded[0])
        self.assertEqual(body_lines(folded), FOLDED)

    def test_on_a_short_screen_down_reaches_the_last_line_and_up_the_first(self):
        term, _ = self.open_c(size=(100, 12))
        term.keys("r")
        shown = lines(term.wait(lambda s: "↑↓" in s and "p models" in s))
        self.assertEqual(next(line for line in reversed(shown) if line), SCROLL_KEYS)
        room = len(body_lines(shown))
        self.assertLess(room, len(OWN))
        self.assertEqual(body_lines(shown), OWN[:room])

        # ↓, j and the wheel each move down a line until the last line is reached
        term.keys("Down")
        shown = lines(term.wait(lambda s: body_lines(lines(s)) == OWN[1:1 + room]))
        term.keys("j")
        term.wait(lambda s: body_lines(lines(s)) == OWN[2:2 + room])
        term.type(WHEEL_DOWN)
        term.wait(lambda s: body_lines(lines(s)) == OWN[3:3 + room])
        term.keys(*["Down"] * len(OWN))
        end = lines(term.wait(lambda s: OWN[-1] in s))
        self.assertEqual(body_lines(end), OWN[-room:])

        # ↑, k and the wheel move back up a line to the first line
        term.keys("Up")
        term.wait(lambda s: body_lines(lines(s)) == OWN[-room - 1:-1])
        term.keys("k")
        term.wait(lambda s: body_lines(lines(s)) == OWN[-room - 2:-2])
        term.type(WHEEL_UP)
        term.wait(lambda s: body_lines(lines(s)) == OWN[-room - 3:-3])
        term.keys(*["Up"] * len(OWN))
        top = lines(term.wait(lambda s: OWN[0] in s))
        self.assertEqual(body_lines(top), OWN[:room])

    def test_p_opens_the_company_list_and_esc_comes_back(self):
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        self.home.write(".agentkit/state/boards.json", boards())
        akconfig.write(self.home, {"mid": {"harness": "claude", "model": "acme-mid-5"},
                                   "bolt": {"harness": "codex", "model": "bolt-3"}},
                       orchestrator="mid", workers=["bolt"], reviewers=["bolt"])
        term, _ = self.open_c(size=(100, 30))
        term.keys("r")
        term.wait("p models")
        term.keys("p")
        listed = lines(term.wait(lambda s: "a add a company" in s and "Acme Mid 5" in s))
        self.assertTrue(listed[0].startswith("agentkit · config · your runs · new seats · models"),
                        listed[0])
        term.keys("Escape")
        back = lines(term.wait("p models"))
        self.assertTrue(back[0].startswith("agentkit · config · your runs · new seats"), back[0])
        term.keys("Escape")
        term.wait("r your runs")

    def test_with_no_board_held_and_none_answering_it_opens_the_same(self):
        state = self.home.path / ".agentkit/state"
        self.assertFalse((state / "boards.json").exists())
        self.assertFalse((state / "matrix.json").exists())
        term, _ = self.open_c(size=(100, 30))
        term.keys("r")
        shown = lines(term.wait(lambda s: "p models" in s and "REVIEWER" in s))
        self.assertEqual(body_lines(shown), OWN)
        self.assertEqual([name for name in ("boards.json", "matrix.json")
                          if (state / name).exists()], [])


if __name__ == "__main__":
    unittest.main()
