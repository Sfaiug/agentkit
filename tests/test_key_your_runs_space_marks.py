"""On `config · your runs · new seats` Space on a builder's or a reviewer's row does what Space does
on that model's mark for that role on `c`: a model not in use is used and one in use no longer,
saved to config.toml's [defaults] at once, and the page then counts for the team as it now is,
the highlight on the model it was on, though the rows above it go; a row whose model the config
no longer holds is refused in one line naming it, the page and config.toml as they were.  The key
line reads `↑↓ move   ␣ mark   p models   esc back`.  Black-box: `AK_BIN` in a terminal in every
colour over tests/test_key_models_own_tables.py's history, with a dead proxy, the highlight read
as tests/test_key_your_runs_highlight.py reads it; fails against /bin/false."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX
from fixtures.akterm import SERVER, Terminal
from test_key_models_own_tables import HEADS, MODELS, NOVA, TEAMS, home_of
from test_key_your_runs_highlight import COLOURED, rested
from test_key_your_runs_screen import AT_100, KEYS, last_line


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class YourRunsSpaceMarks(unittest.TestCase):
    def open(self, home):
        """`r your runs` on `c` over `home`, on 100 by 30 cells, the highlight on its first row."""
        self.addCleanup(home.close)
        self.home, self.term = home, Terminal(home, size=(100, 30), env=COLOURED)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait("r your runs")
        self.term.keys("r")
        self.assertEqual(last_line(rested(self.term, AT_100[3:4], AT_100)), KEYS)

    def test_a_reviewer_marked_counts_the_tasks_it_reviewed_in_every_table(self):
        home = home_of(TEAMS)       # echo at the effort it reviewed at, which its tasks recorded
        akconfig.write(home, {**MODELS, "echo": {**MODELS["echo"], "effort": "medium"}},
                       orchestrator="nova", workers=["bolt"], reviewers=["crux"])
        self.open(home)
        rested(self.term, AT_100[12:13], AT_100, *["Down"] * 5)
        # echo's 30 tasks, none live, join the team's and nova's and bolt's: 74 of them, 23 live
        echo = "■" + AT_100[12][1:]
        rested(self.term, [echo], [
            "Your team now: 23 of 74 tasks went live, 8.8 h per task live, 3.2 h of it waiting",
            *AT_100[1:3], f"● {NOVA} high     54        33%           -         -   8.2 h      -",
            *AT_100[4:7], f"■ Bolt 3 max{' ' * 16}74        31%                22%      2.5  8.8 h"
                          "      -", *AT_100[8:12], echo, *AT_100[13:]], "Space")
        self.assertEqual(akconfig.read(home)["defaults"]["reviewers"], ["crux", "echo"])

    def test_the_only_builder_unmarked_leaves_a_team_with_none(self):
        self.open(home_of(TEAMS))
        rested(self.term, AT_100[7:8], AT_100, "Down", "Down")
        # no task had no builder; bolt's and gale's rows count the teams beside nova and crux
        bolt = "□" + AT_100[7][1:]
        rested(self.term, [bolt], [
            "Your team now has no task yet", "",
            f"ORCHESTRATOR{' ' * 13}{HEADS['ORCHESTRATOR']}", f"● {NOVA} high      0", "",
            *AT_100[6:7], bolt, *AT_100[8:10],
            f"REVIEWER{' ' * 17}{HEADS['REVIEWER']}", f"■ Crux 2[ medium{' ' * 13}0",
            *AT_100[-4:]], "Space")
        self.assertEqual(akconfig.read(self.home)["defaults"]["workers"], [])

    def test_a_model_no_longer_configured_is_refused_naming_it(self):
        self.open(home_of(TEAMS))
        written = (self.home.path / ".agentkit/config.toml").read_bytes()
        rested(self.term, AT_100[8:9], AT_100, *["Down"] * 3)
        rested(self.term, AT_100[8:9], [*AT_100, "", "  gale is no longer in the config"],
               "Space")
        self.assertEqual((self.home.path / ".agentkit/config.toml").read_bytes(), written)


if __name__ == "__main__":
    unittest.main()
