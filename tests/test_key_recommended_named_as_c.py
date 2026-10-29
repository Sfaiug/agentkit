"""`r recommended` on `c` opens a page named as `c`'s other pages are, `config · recommended ·
new seats` in a window of its own, and so are the pages it opens, `p` and a row's why.
Black-box, as tests/test_key_models_answer.py, judged by the header.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, boards, lines

TITLE = "agentkit · config · recommended · new seats"


class RecommendedNamedAsC(unittest.TestCase):
    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_recommended_and_the_pages_it_opens_are_named_as_cs_pages(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")
        home.write(".agentkit/state/boards.json", boards())
        akconfig.write(home, {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
                              "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}})
        term = Terminal(home, size=(100, 60), env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        named = lambda shown: lambda screen: shown in screen and lines(screen)[0].startswith(TITLE)
        term.wait("esc leave")
        for key, shown in [("c", "r recommended"), ("r", named("comparing all 4 models")),
                           ("p", named("models to compare")),
                           ("Escape", named("comparing all 4 models")),
                           ("Enter", named("\n  why "))]:   # the pointer starts on a pick
            term.keys(key)
            term.wait(shown)


if __name__ == "__main__":
    unittest.main()
