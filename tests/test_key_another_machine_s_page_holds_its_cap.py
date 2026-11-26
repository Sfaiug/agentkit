"""A listed machine's page on `c` holds its cap on runs at once (`[machines."NAME"] max_runs`).

Black-box: AK_BIN runs under a terminal in a temporary HOME with invented machines. Under its
two work marks, `runs at once` reads `no limit` or the cap; Enter opens a field where a whole
number of 1 or more sets `max_runs`, 0 or nothing typed takes it off, Esc cancels, and anything
else is refused in a sentence without changing config.toml.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnotherMachinesPageHoldsItsCap(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        self.config = self.write_config()

    def write_config(self, linux=""):
        return akconfig.write(
            self.home, ["fable"],
            extra=f"[machines.acme-linux]\n{linux}[machines.acme-other]\n",
        )

    def open_machine(self):
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen
                       and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines" in screen
                       and "acme-linux" in screen and "esc back" in screen)
        self.term.keys("Down")
        self.term.wait("› acme-linux")
        self.term.keys("Enter")
        return self.term.wait(lambda screen: "config · machines · acme-linux" in screen
                              and "builds and reviews" in screen and "tests" in screen
                              and "esc back" in screen)

    def leave(self):
        self.term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)

    def test_a_cap_is_set_read_back_and_taken_off_again(self):
        before = self.config.read_bytes()
        shown = " ".join(self.open_machine().split())
        self.assertIn("runs at once no limit", shown)
        self.assertLess(shown.index("builds and reviews"), shown.index("tests"))
        self.assertLess(shown.index("tests"), shown.index("runs at once"))
        self.assertEqual(self.config.read_bytes(), before)

        self.term.keys("Down", "Down")
        on_cap = self.term.wait("› runs at once")
        keys = next(line for line in reversed(on_cap.splitlines()) if line.strip())
        self.assertIn("⏎ open", keys)
        self.assertNotIn("␣", keys)

        # Typing a whole number of 1 or more sets max_runs on this machine alone.
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.type("2")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "runs at once 2" in " ".join(screen.split())
                       and "⏎ open" in screen)
        cfg = akconfig.read(self.home)
        self.assertEqual(cfg["machines"]["acme-linux"]["max_runs"], 2)
        self.assertNotIn("max_runs", cfg["machines"]["acme-other"])
        self.leave()

        # Reopening reads the saved cap back from config.toml; Esc in the field keeps it.
        reopened = " ".join(self.open_machine().split())
        self.assertIn("runs at once 2", reopened)
        before_esc = self.config.read_bytes()
        self.term.keys("Down", "Down")
        self.term.wait("› runs at once")
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.type("9")
        self.term.keys("Escape")
        self.term.wait(lambda screen: "runs at once 2" in " ".join(screen.split())
                       and "⏎ open" in screen)
        self.assertEqual(self.config.read_bytes(), before_esc)

        # 0 takes the line off.
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.type("0")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "runs at once no limit" in " ".join(screen.split())
                       and "⏎ open" in screen)
        self.assertNotIn("max_runs", akconfig.read(self.home)["machines"]["acme-linux"])

        # Nothing typed also takes the line off.
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.type("3")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "runs at once 3" in " ".join(screen.split())
                       and "⏎ open" in screen)
        self.assertEqual(akconfig.read(self.home)["machines"]["acme-linux"]["max_runs"], 3)
        self.term.keys("Enter")
        self.term.wait("⏎ save")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "runs at once no limit" in " ".join(screen.split())
                       and "⏎ open" in screen)
        self.assertNotIn("max_runs", akconfig.read(self.home)["machines"]["acme-linux"])
        self.leave()

    def test_a_word_or_bad_number_is_refused_and_changes_nothing(self):
        self.config = self.write_config("max_runs = 2\n")
        before = self.config.read_bytes()
        self.open_machine()
        self.term.keys("Down", "Down")
        self.term.wait("› runs at once")
        for bad in ("two", " ", "-1", "1.5"):
            with self.subTest(typed=bad):
                self.term.keys("Enter")
                self.term.wait("⏎ save")
                self.term.keys("-l", "--", bad)
                self.term.keys("Enter")
                screen = self.term.wait(lambda s: "whole number" in " ".join(s.split())
                                        and "⏎ open" in s)
                self.assertIn("runs at once 2", " ".join(screen.split()))
                self.assertEqual(self.config.read_bytes(), before)
        self.leave()


if __name__ == "__main__":
    unittest.main()
