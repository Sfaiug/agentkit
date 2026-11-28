"""`r your runs` on `c` opens `config · your runs · <seat>` (or `· new seats`): the lines
`ak models` prints for that seat's team now, at the screen's width, folding as the command's
fold, asking no board; `p` opens the company list and Esc goes back.  Black-box: `AK_BIN` in a
terminal over tests/test_key_models_own_tables.py's history, with a dead proxy; fails against
/bin/false."""

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
body_lines = lambda shown: shown[2:max((i for i, l in enumerate(shown) if l), default=2) - 1]
last_line = lambda shown: next((l for l in reversed(shown) if l), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class YourRunsScreen(unittest.TestCase):
    def setUp(self):
        self.home = home_of(TEAMS)
        self.addCleanup(self.home.close)

    def open_c(self, size=(100, 30), seat=None):
        term = Terminal(self.home, *(("attach", "--overlay") if seat else ()), size=size,
                        env={**ENV, **({"AGENTKIT_SESSION": seat} if seat else {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        return term, lines(term.wait("r your runs"))

    def test_r_shows_the_team_line_and_the_three_tables_headings(self):
        term, _ = self.open_c()
        term.keys("r")
        shown = lines(term.wait(lambda s: "p models" in s and "REVIEWER" in s))
        self.assertTrue(shown[0].startswith("agentkit · config · your runs · new seats"), shown[0])
        self.assertEqual((body_lines(shown), last_line(shown)), (OWN, KEYS))
        state = self.home.path / ".agentkit/state"
        self.assertEqual([n for n in ("boards.json", "matrix.json") if (state / n).exists()], [])
        term.resize(100, 12)
        short = lines(term.wait(
            lambda s: "Your team now:" in s and "p models" in s and "REVIEWER" not in s))
        self.assertEqual((body_lines(short), last_line(short)), (OWN[:len(body_lines(short))], KEYS))
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

    def test_p_opens_the_company_list_and_esc_comes_back(self):
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        self.home.write(".agentkit/state/boards.json", boards())
        akconfig.write(self.home, {"mid": {"harness": "claude", "model": "acme-mid-5"},
                                   "bolt": {"harness": "codex", "model": "bolt-3"}},
                       orchestrator="mid", workers=["bolt"], reviewers=["bolt"])
        term, _ = self.open_c()
        for key, want, head in (
            ("r", "p models", "agentkit · config · your runs · new seats"),
            ("p", lambda s: "a add a company" in s and "Acme Mid 5" in s,
             "agentkit · config · your runs · new seats · models"),
            ("Escape", "p models", "agentkit · config · your runs · new seats"),
            ("Escape", "r your runs", "agentkit · config"),
        ):
            term.keys(key)
            self.assertTrue(lines(term.wait(want))[0].startswith(head))


if __name__ == "__main__":
    unittest.main()
