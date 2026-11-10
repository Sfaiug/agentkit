"""On 40 cells `r recommended` on `c` and its why read `agentkit · recommended · new seats`: a
name too wide sheds where you came from before it is cut.  Black-box; fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, boards, lines

HEADER = re.compile(r"agentkit · recommended · new seats +\d\d:\d\d$")


class NarrowHeaderKeepsWhereYouAre(unittest.TestCase):
    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_on_40_cells_recommended_and_its_why_shed_config_whole(self):
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
        headed = lambda shown: lambda screen: shown in screen and HEADER.match(lines(screen)[0])
        term.wait("esc leave")
        for key, shown in [("c", "r recommended"), ("r", headed("comparing all 4")),
                           ("Enter", headed("\n  why "))]:   # the pointer starts on a pick
            term.keys(key)
            term.wait(shown)


if __name__ == "__main__":
    unittest.main()
