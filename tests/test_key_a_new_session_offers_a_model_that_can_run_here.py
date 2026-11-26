"""A new seat is offered a model whose harness's program is installed here: where the default
orchestrator's is missing and another model's is not, `n` offers that other model, Enter starts
it, and `ak orch NAME --dry-run` says the default was skipped as not installed, the way it says
so of a default off in the model list.  With every program installed the default is offered.

A newcomer with one harness installed got a seat on the default's missing one, whose pane said
only that the harness ended.  Black-box: the program `AK_BIN` names runs from outside
(tests/fixtures/akbin.py), its menu on a terminal of tests/fixtures/akterm.py, its harnesses
tests/fixtures/fakeadapter.py's; Claude's program is missing once its manifest names it at a
path where nothing is, so no Claude the host installed stands in for it.
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
NAMED = 'version = ["claude", '     # the program claude.toml's [update] runs


class OffersWhatRunsHere(unittest.TestCase):
    """opus, on claude, orchestrates by default; astra, on codex, is the other model."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, ["opus", "astra"])
        self.shipped = self.fakes["claude"].manifest.read_text()
        self.assertEqual(self.shipped.count(NAMED), 1, "the shipped claude.toml's [update] changed")

    def name_claude(self, program):
        """Claude's manifest names `program` as the program its harness runs."""
        self.fakes["claude"].manifest.write_text(
            self.shipped.replace(NAMED, f"version = [{fakeadapter.toml(str(program))}, "))

    def uninstall_claude(self):
        self.name_claude(self.home.root / "gone" / "claude")

    def picked(self):
        """The line `ak orch fix-api --dry-run` names the orchestrator on."""
        done = self.home.ak("orch", "fix-api", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        return next(line for line in done.out.splitlines() if line.startswith("orch: "))

    def test_a_dry_run_skips_the_default_whose_program_is_missing_and_says_so(self):
        self.uninstall_claude()
        line = self.picked()
        self.assertTrue(line.startswith("orch: astra ("), line)
        self.assertIn("skipped opus: claude is not installed", line)
        self.assertNotIn("off in the model list", line)

    def test_a_program_it_may_not_reach_or_name_is_not_installed(self):
        hidden = self.home.root / "hidden"
        hidden.mkdir(mode=0)        # a directory this user may not search
        self.addCleanup(hidden.chmod, 0o700)
        for program in (hidden / "claude", f"{self.home.bin / 'claude'}\0", "claude\0"):
            with self.subTest(program=program):
                self.name_claude(program)
                line = self.picked()
                self.assertTrue(line.startswith("orch: astra ("), line)
                self.assertIn("skipped opus: claude is not installed", line)

    def test_with_every_program_installed_the_default_is_offered(self):
        line = self.picked()
        self.assertTrue(line.startswith("orch: opus ("), line)
        self.assertNotIn("skipped", line)

    def test_a_default_off_in_the_model_list_is_skipped_as_today(self):
        akconfig.write(self.home, ["opus", "astra"], settings={"models_off": ["claude-opus-5-5"]})
        line = self.picked()
        self.assertTrue(line.startswith("orch: astra ("), line)
        self.assertIn("skipped opus: off in the model list", line)

    def menu_row(self):
        """The new seat's row `n` makes on the menu, and the menu."""
        menu = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        menu.wait("esc leave")
        menu.keys("n")
        rows = menu.wait(ROW_KEYS).splitlines()
        return next(row for row in rows if row.startswith("›")), menu

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_n_offers_the_model_whose_program_is_installed_and_enter_starts_it(self):
        self.uninstall_claude()
        row, menu = self.menu_row()
        self.assertRegex(row, r" Astra \w+ +new$")
        menu.type("fix-api")
        menu.keys("Enter")
        path = self.home.path / ".agentkit/state/session-fix-api.json"
        deadline = time.monotonic() + 30
        while not path.exists():
            self.assertLess(time.monotonic(), deadline,
                            f"fix-api never started; the terminal shows:\n{menu.screen()}")
            time.sleep(0.05)
        self.assertEqual(json.loads(path.read_text())["orchestrator"], "astra")

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_n_offers_the_default_with_every_program_installed(self):
        row, _ = self.menu_row()
        self.assertRegex(row, r" Opus 5\.5 \w+ +new$")


if __name__ == "__main__":
    unittest.main()
