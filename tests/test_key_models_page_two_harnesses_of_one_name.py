"""On `Models`, two harnesses whose manifests give one name each keep a row of their own: ↓ and
Enter on the second open its catalog, and Esc brings the highlight back to it.

Before, the page knew a row again by its label alone, so the highlight went back to the first of
the two and the second's catalog could not be opened from the keyboard.  Black-box: the program
`AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py.  The terminal has no colour (NO_COLOR).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsPageTwoHarnessesOfOneName(unittest.TestCase):
    def test_the_second_opens_its_own_catalog(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, **dict.fromkeys(("acme-stable", "acme-preview"), "pass"))
        for fake in fakes.values():
            fake.manifest.write_text('name = "Acme"\n' + fake.manifest.read_text())
        akconfig.write(home, {name: {"model": name, "label": name.title(), "harness": harness,
                                     "provider": "acme"}
                              for name, harness in zip(("alpha", "beta"), fakes)})
        term = Terminal(home, "attach", "--overlay", env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: "Models" in screen and "esc back" in screen)
        term.keys("Down", "Down")
        term.wait("› Models")
        term.keys("Enter")
        term.wait(lambda screen: "config · models" in screen and "› Acme  Alpha" in screen)
        term.keys("Down", "Enter")
        screen = term.wait(lambda screen: "■ Alpha" in screen or "■ Beta" in screen)
        self.assertIn("›   ■ Beta", screen)
        term.keys("Escape")
        term.wait(lambda screen: "› Acme  Beta" in screen and "■" not in screen)


if __name__ == "__main__":
    unittest.main()
