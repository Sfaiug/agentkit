"""On 40 cells `r your runs` on `c` reads `agentkit · your runs · new seats`, and `p` on it
`agentkit · new seats · models`: a name too wide sheds where you came from before it is cut.
Black-box; fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from fixtures.akboards import ENV, boards, lines

RUNS_HEADER = re.compile(r"agentkit · your runs · new seats +\d\d:\d\d$")
MODELS_HEADER = re.compile(r"agentkit · new seats · models +\d\d:\d\d$")


class NarrowHeaderKeepsWhereYouAre(unittest.TestCase):
    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_on_40_cells_your_runs_and_models_shed_where_you_came_from_whole(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        home.write(".agentkit/state/boards.json", boards())
        akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
                              "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}})
        term = Terminal(home, size=(40, 60), env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        headed = lambda pat, shown: lambda screen: shown in screen and pat.match(lines(screen)[0])
        term.wait("esc leave")
        for key, shown in [("c", "r your runs"), ("r", headed(RUNS_HEADER, "p models")),
                           ("p", headed(MODELS_HEADER, "+ add a company"))]:
            term.keys(key)
            term.wait(shown)


if __name__ == "__main__":
    unittest.main()
