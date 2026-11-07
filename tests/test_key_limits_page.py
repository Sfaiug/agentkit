"""`c` shows `review_rounds`, `executor_lines` and `orchestrator_lines` on one `Limits` row, at a glance, and
Enter there opens `config · limits`: a row each under a plain name, its value and `default N`
where that is not ak's default, the pointed one's meaning and board rows under the rows.  ← and
→ move the pointed one a step (tests/test_key_limits_arrow_steps.py), saved to config.toml at
once, every other key kept; both line limits end with `no limit`, and a save that fails changes
nothing and says why.

The owner's ask of 3 Nov 2026: the keys' names were unclear to users.  Black-box: the program
`AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py, judged by the screen and config.toml.  The terminal has no colour
(NO_COLOR).  This test fails against `/bin/false`.
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
NAMES = ("Review rounds", "Max lines per executor task", "Max lines per orchestrator task")
WIDE = max(map(len, NAMES))
MEANS = ("The review rounds a change has before it goes back to its orchestrator to split or "
         "re-scope; it moves first round, unmerged, hours to merge.")


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def row(name, value, on=False):
    return f"{'›' if on else ' '} {name:<{WIDE}}  {value}"


# Settings on the settings screen are each shown with ak's default and the board
# numbers it moves. [30 Oct 2026]
@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LimitsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")

    def c(self, settings=None, size=(100, 40)):
        """`c` in a window of its own, over a config.toml setting `settings`."""
        akconfig.write(self.home, MODELS, settings=settings)
        return self.opened(size)

    def opened(self, size):
        term = Terminal(self.home, size=size, env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        return term

    def limits(self, term):
        """`config · limits` opened from `c`."""
        term.keys(*["j"] * 30)       # Limits is the last config row.
        term.wait("› Limits")
        term.keys("Enter")
        # the page's own key line, drawn after its rows: the header can read `config · limits`
        # over `c`'s rows while the page reads what it shows
        return term.wait("←→ value")

    def moved(self, term, name, arrows, value):
        """`name` pointed, `arrows` pressed there, once its value reads `value`."""
        term.keys(*["j"] * NAMES.index(name))
        term.wait(f"› {name}")
        term.keys(*arrows)
        return lines(term.wait(lambda screen: any(
            line.startswith(f"› {name:<{WIDE}}  ") and f" {value} " in f"{line} "
            for line in lines(screen))))

    def test_c_shows_one_limits_row_with_the_three_values(self):
        shown = lines(self.c().wait("Limits"))
        self.assertIn("  Limits        review 3 rounds · executor 300 lines · orchestrator 50 "
                      "lines", shown)
        for gone in ("review_rounds", "executor_lines", "orchestrator_lines"):
            self.assertFalse([line for line in shown if line.split()[:1] == [gone]], shown)

    def test_enter_on_limits_opens_the_page_with_the_three_plain_names(self):
        shown = lines(self.limits(self.c({"orchestrator_lines": 0})))
        self.assertIn("agentkit · config · limits", shown[0])
        self.assertEqual([line for line in shown if any(name in line for name in NAMES)],
                         [row(NAMES[0], "◂ 3 ▸", on=True), row(NAMES[1], "300"),
                          row(NAMES[2], "off default 50")])
        self.assertIn(MEANS, " ".join(line.strip() for line in shown))
        self.assertEqual(akconfig.read(self.home)["orchestrator_lines"], 0)

    def test_the_pointer_off_every_row_takes_the_note_away(self):
        term = self.c()
        self.limits(term)
        term.wait(lambda screen: MEANS in " ".join(screen.split()))
        term.type("\x1b[<35;8;1M")      # onto the header: the highlight goes out, and the note
        term.wait(lambda screen: MEANS not in " ".join(screen.split()))

    def test_on_a_narrow_terminal_each_value_folds_under_its_name_never_cut(self):
        shown = lines(self.limits(self.c(
            {"review_rounds": 4, "executor_lines": 1000, "orchestrator_lines": 0}, size=(40, 50))))
        at = shown.index(f"› {NAMES[0]}")
        self.assertEqual(shown[at:at + 6], [
            f"› {NAMES[0]}", "    ◂ 4 ▸ default 3", f"  {NAMES[1]}", "    1000 default 300",
            f"  {NAMES[2]}", "    off default 50"])

    def test_moving_to_1000_lines_per_executor_task_saves_it(self):
        term = self.c({"executor_lines": 900, "max_runs": 7, "custom_flag": True})
        self.limits(term)
        shown = self.moved(term, NAMES[1], ("Right",), "1000")
        self.assertIn(row(NAMES[1], "◂ 1000 ▸ default 300", on=True), shown)
        saved = akconfig.read(self.home)
        self.assertEqual((saved["executor_lines"], saved["max_runs"], saved["custom_flag"]),
                         (1000, 7, True))
        term.keys("Escape")
        term.wait("executor 1000 lines")

    def test_moving_off_lines_per_orchestrator_task_saves_zero(self):
        term = self.c()
        self.limits(term)
        shown = self.moved(term, NAMES[2], ("Left",) * 2, "off")
        self.assertIn(row(NAMES[2], "off ▸ default 50", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["orchestrator_lines"], 0)
        term.wait(lambda screen: "The orchestrator builds nothing; executors build every change."
                  in " ".join(screen.split()))

    def test_moving_executors_off_saves_zero_and_explains_who_builds(self):
        term = self.c()
        self.limits(term)
        shown = self.moved(term, NAMES[1], ("Left",) * 3, "off")
        self.assertIn(row(NAMES[1], "off ▸ default 300", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["executor_lines"], 0)
        term.wait(lambda screen: "Executors are off; the orchestrator builds every change itself."
                  in " ".join(screen.split()))
        term.keys("Escape")
        term.wait("executor off")

    def test_the_second_builder_cannot_be_switched_off(self):
        # the other on its lowest step over 0, so the one ← that would take it to 0 is refused
        for off, target, (key, low) in (("executor_lines", NAMES[2], ("orchestrator_lines", 25)),
                                        ("orchestrator_lines", NAMES[1], ("executor_lines", 100))):
            with self.subTest(off=off):
                term = self.c({off: 0, key: low})
                given = (self.home.path / ".agentkit/config.toml").read_bytes()
                self.limits(term)
                self.moved(term, target, ("Left",), str(low))
                term.wait("cannot both be 0")
                self.assertEqual((self.home.path / ".agentkit/config.toml").read_bytes(), given)

    def test_moving_review_off_saves_zero_and_explains_checks_only(self):
        term = self.c()
        self.limits(term)
        shown = self.moved(term, NAMES[0], ("Left",) * 3, "off")
        self.assertIn(row(NAMES[0], "off ▸ default 3", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["review_rounds"], 0)
        term.wait(lambda screen: "A change lands on its checks; no reviewer." in " ".join(screen.split()))
        term.keys("Escape")
        term.wait("review off")

    def test_both_line_limits_end_with_no_limit_and_save_it(self):
        for key, name in zip(("executor_lines", "orchestrator_lines"), NAMES[1:]):
            with self.subTest(key=key):
                term = self.c()
                self.limits(term)
                shown = self.moved(term, name, ("Right",) * 20, "no limit")
                self.assertIn(row(name, "◂ no limit default " + ("300" if key == "executor_lines" else "50"),
                                  on=True), shown)
                self.assertEqual(akconfig.read(self.home)[key], "no limit")
                term.keys("Escape")
                term.wait(("executor" if key == "executor_lines" else "orchestrator") + " no limit")

    def test_a_pick_that_cannot_be_saved_changes_nothing_and_says_why(self):
        term = self.c()
        given = (self.home.path / ".agentkit/config.toml").read_bytes()
        blocked = self.home.path / ".agentkit/config.tmp"
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        self.limits(term)
        term.keys("Right")
        shown = lines(term.wait("Is a directory"))
        self.assertIn(row(NAMES[0], "◂ 3 ▸", on=True), shown)
        self.assertEqual((self.home.path / ".agentkit/config.toml").read_bytes(), given)


if __name__ == "__main__":
    unittest.main()
