"""A new seat's builders and reviewers are models whose programs are installed here: with the
marked ones' programs missing and one other model's installed, `n` shows that model on the new
row's `build and review`, names none whose program is missing, and Enter makes the seat with it;
with every program installed, the row is today's.

Black-box: the program `AK_BIN` names runs from outside (tests/fixtures/akbin.py), its menu on a
terminal of tests/fixtures/akterm.py, its harnesses tests/fixtures/fakeadapter.py's; a missing
program is named at a path under the throwaway Home where nothing is, so no install on the host
stands in for it.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

ROW_KEYS = "  ⏎ start   tab models   esc back"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class BuildersCanRunHere(unittest.TestCase):
    """opus (claude) and astra (codex) are marked in [defaults]; spark (muse) is offered too."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass", muse="pass")
        akconfig.write(self.home, ["opus", "astra", "spark"], workers=["opus", "astra"])

    def uninstall(self, *harnesses):
        for harness in harnesses:
            manifest = self.fakes[harness].manifest
            text, named = manifest.read_text(), f'version = ["{harness}", '
            self.assertEqual(text.count(named), 1, f"{harness}.toml's [update] changed")
            gone = fakeadapter.toml(str(self.home.root / "gone" / harness))
            manifest.write_text(text.replace(named, f"version = [{gone}, "))

    def new_row(self):
        """The highlighted new row, the crew line under it, and the menu."""
        menu = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        menu.wait("esc leave")
        menu.keys("n")
        rows = menu.wait(ROW_KEYS).splitlines()
        at = next(n for n, row in enumerate(rows) if row.startswith("›"))
        return rows[at], rows[at + 1], menu

    def test_with_marked_programs_missing_n_shows_and_starts_the_installed_model(self):
        self.uninstall("claude", "codex")
        row, under, menu = self.new_row()
        self.assertRegex(row, r"^› 1  ▏[a-z-]+ +Spark 1\.3 Contributor xhigh  new$")
        self.assertEqual(under, "     build and review: Spark 1.3 Contributor xhigh")
        menu.type("fix-api")
        menu.keys("Enter")
        path = self.home.path / ".agentkit/state/session-fix-api.json"
        deadline = time.monotonic() + 30
        while not path.exists():
            self.assertLess(time.monotonic(), deadline,
                            f"fix-api never started; the terminal shows:\n{menu.screen()}")
            time.sleep(0.05)
        record = json.loads(path.read_text())
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("spark", ["spark"], ["spark"]))

    def test_with_every_program_installed_the_row_is_todays(self):
        row, under, _ = self.new_row()
        self.assertRegex(row, r"^› 1  ▏[a-z-]+ +Opus 5\.5 xhigh  new$")
        self.assertEqual(under, "     build and review: Opus 5.5 xhigh, 6 Astra xhigh")


if __name__ == "__main__":
    unittest.main()
