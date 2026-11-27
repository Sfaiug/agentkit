"""`config · limits` holds `rescope_findings`
(tests/test_key_many_findings_end_a_run_for_rescoping.py) on a row after `Extra rounds with one or
two findings left`, drawn as that row is: on a fresh home `Findings that end a run for rescoping`
at 6, its meaning under it, then its table (tests/test_key_limits_first_issues_table.py), ← and
→ stepping it by one from 0 with no top, saved to config.toml at once.

The owner's ask of 20 Nov 2026: "The user can choose how many findings should force a rescope.";
22 Nov 2026: "Let the page count on."
Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), its
harnesses the fakes of tests/fixtures/fakeadapter.py, judged by the screen and config.toml.  The
terminal has no colour (NO_COLOR).  This test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}
EXTRA, NAME = "Extra rounds with one or two findings left", "Findings that end a run for rescoping"
WIDE = len(EXTRA)          # the widest name on the page
MEANING = ("The blocking findings a task's review leaves that end its run for rescoping, 0 "
           "never.")


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def flat(screen):
    """The screen's words, each run of spaces and line ends one space: wrapped words read on."""
    return " ".join(screen.split())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RescopeFindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")

    def pointed(self, settings=None):
        """`config · limits` from `c` over a config.toml setting `settings`, the pointer on the
        row, in a window of its own."""
        akconfig.write(self.home, MODELS, settings=settings)
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys(*["j"] * 7)     # Limits is the eighth row, the two models first.
        term.wait("› Limits")
        term.keys("Enter")
        term.wait("←→ value")
        term.keys(*["j"] * 4)
        term.wait(f"› {NAME}")
        return term

    def shows(self, term, drawn):
        """Once the pointed row reads `drawn`: the screen's lines."""
        return lines(term.wait(lambda screen: f"› {NAME:<{WIDE}}  {drawn}" in lines(screen)))

    def test_a_fresh_home_shows_6_after_extra_rounds_with_its_meaning(self):
        term = self.pointed()
        shown = self.shows(term, "◂ 6 ▸")
        names = [line[2:].split("  ")[0] for line in shown if line[2:].startswith((EXTRA, NAME))]
        self.assertEqual(names, [EXTRA, NAME])
        # under it, its table of no task yet (tests/test_key_limits_first_issues_table.py)
        self.assertIn(f"› {NAME} ◂ 6 ▸ {MEANING} What your tasks took, by the issues their first "
                      "review found · none yet ↑↓ limit", flat("\n".join(shown)))
        self.assertNotIn("rescope_findings", akconfig.read(self.home))

    def test_right_saves_7(self):
        term = self.pointed()
        self.shows(term, "◂ 6 ▸")
        term.keys("Right")
        self.shows(term, "◂ 7 ▸ default 6")
        self.assertEqual(akconfig.read(self.home)["rescope_findings"], 7)

    def test_from_20_left_saves_19_and_right_then_20(self):
        term = self.pointed({"rescope_findings": 20})
        self.shows(term, "◂ 20 ▸ default 6")
        for arrow, value in (("Left", 19), ("Right", 20)):
            term.keys(arrow)
            self.shows(term, f"◂ {value} ▸ default 6")
            self.assertEqual(akconfig.read(self.home)["rescope_findings"], value)

    def test_left_from_1_saves_0_and_there_moves_nothing(self):
        term = self.pointed({"rescope_findings": 1})
        self.shows(term, "◂ 1 ▸ default 6")
        term.keys("Left")
        self.shows(term, "off ▸ default 6")
        self.assertEqual(akconfig.read(self.home)["rescope_findings"], 0)
        term.keys("Left", "Right")      # ← at 0 moves nothing: → takes 1
        self.shows(term, "◂ 1 ▸ default 6")
        self.assertEqual(akconfig.read(self.home)["rescope_findings"], 1)


if __name__ == "__main__":
    unittest.main()
