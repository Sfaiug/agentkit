"""A feature list that could not be refreshed says so on the features screen wherever the
highlight is, however many features the project has: with more features than fit and the last
one highlighted, the screen drawn still says why its rows are stale.

`menu.show_features` runs in-process on a 12-line terminal over ACME's 30 features as an earlier
`list` answered them, its last `list` having failed; the keys are fed to it and each screen it
draws is kept.  Nothing here runs a features command, reads a keyboard or touches a real project.
"""

from pathlib import Path
import sys
import time
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import menu, terminal

ACME = Path("/nonexistent/code/ACME")
FEATURES = [{"id": f"f{number}", "name": f"Feature {number}", "you": False, "everyone": False}
            for number in range(1, 31)]
FAILED = "list: no answer in 20 s"


class RefreshErrorShown(unittest.TestCase):
    def setUp(self):
        menu._SWITCHES[str(ACME)] = {"rows": FEATURES, "error": FAILED, "asked": time.monotonic(),
                                     "going": False, "set": 0, "flips": {}}
        self.addCleanup(menu._SWITCHES.pop, str(ACME), None)

    def drawn(self, keys):
        """Each screen show_features drew while `keys` were read, its lines as shown."""
        screens, keys = [], iter(keys)

        def frame(name, body=(), keyline="esc back", filled=0, **_kw):
            screens.append([terminal.ANSI.sub("", line) for line in body])
        with mock.patch.object(terminal, "height", lambda: 12), \
                mock.patch.object(terminal, "layout_width", lambda *_: 80), \
                mock.patch.object(terminal, "frame", frame), \
                mock.patch.object(terminal, "read_key", lambda *_, **_kw: next(keys)), \
                mock.patch.object(menu, "features_run", lambda checkout, *words: (None, FAILED)):
            menu.show_features(ACME)
        return screens

    def test_the_last_feature_highlighted_still_shows_the_failed_list(self):
        screens = self.drawn([terminal.Key("down")] * (len(FEATURES) - 1) + [terminal.Key("esc")])
        self.assertEqual(len(screens), len(FEATURES))
        last = screens[-1]
        self.assertIn("Feature 30", next(line for line in last if line.startswith("›")), last)
        for lines in screens:                  # wherever the highlight was
            self.assertIn(f"  {FAILED}", lines)


if __name__ == "__main__":
    unittest.main()
