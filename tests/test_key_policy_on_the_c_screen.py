"""`c` shows and sets `rounds`, `review_lines` and `seat_lines`: a row each, in config.POLICY's
order, with its value, `default N` where that is not ak's default and the board rows it moves;
the pointed row opens what the number means under it.  ←/→ step the pointed number one along,
saved to config.toml at once, the row saying `saved`; a step under its floor, or that would put
`seat_lines` over `review_lines`, changes nothing and saves nothing.  The key line names the
step keys there, and Enter and Space do nothing there.

The owner's rule of 30 Oct 2026.  Black-box: the program `AK_BIN` names, in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, judged by
the screen and config.toml; a key sent after another is read after it, so `Left` then `Right`
landing one over the floor proves the `Left` counted nothing.  The terminal has no colour
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
ROUNDS = "moves first round, unmerged, hours to merge"
REVIEW = "moves first round, merged"
SEAT = "moves built"
MEANS = {"rounds": "    the review rounds a change has before it goes back to its orchestrator to "
                   "split or re-scope",
         "review_lines": "    the most added lines a first review reads",
         "seat_lines": "    the added lines a seat's own change stays under"}
FAR = 6                # j presses from the first model to `rounds`: the other, then four rows
STEP_KEYS = "  ↑↓ move   ←→ step   r recommended   a apply to all sessions   esc back"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def row(name, value, aside="", said="", moves=ROUNDS, on=False):
    return f"{'›' if on else ' '} {name:<12}  {value:<3}  {aside:<11}  {said:<5}  {moves}"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PolicyOnC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")

    def c(self, settings=None, size=(100, 30)):
        """`c` in a window of its own, over a config.toml setting `settings`."""
        akconfig.write(self.home, MODELS, settings=settings)
        return self.opened(size)

    def opened(self, size=(100, 30)):
        term = Terminal(self.home, size=size, env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        return term

    def to(self, term, name):
        """The highlight on `name`'s row."""
        term.keys(*["j"] * (FAR + list(MEANS).index(name)))
        term.wait(f"› {name}")

    def test_the_rows_show_in_order_at_their_defaults_each_with_what_it_moves(self):
        shown = lines(self.c().wait("seat_lines"))
        at = shown.index(row("rounds", 3).rstrip())
        self.assertEqual(shown[at - 1].strip(), "GPT-6-Astra")     # Weekly audit's value, wrapped
        self.assertEqual(shown[at:at + 3], [row("rounds", 3), row("review_lines", 300, moves=REVIEW),
                                            row("seat_lines", 50, moves=SEAT)])
        self.assertFalse(set(MEANS.values()) & set(shown), shown)   # nothing pointed at, none open

    def test_the_pointed_row_opens_its_meaning_and_names_the_step_keys(self):
        term = self.c()
        self.to(term, "rounds")
        for name, value, moves in (("rounds", 3, ROUNDS), ("review_lines", 300, REVIEW),
                                   ("seat_lines", 50, SEAT)):
            shown = lines(term.wait(MEANS[name]))
            at = shown.index(row(name, value, moves=moves, on=True))
            self.assertEqual(shown[at + 1], MEANS[name])
            self.assertEqual(set(MEANS.values()) & set(shown), {MEANS[name]})
            self.assertEqual(next(line for line in reversed(shown) if line), STEP_KEYS)
            term.keys("j")

    def test_rounds_steps_to_four_saved_then_back_to_three(self):
        term = self.c()
        self.to(term, "rounds")
        term.keys("Right")
        shown = lines(term.wait("default 3"))
        self.assertIn(row("rounds", 4, "default 3", "saved", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["rounds"], 4)

        # the next key ends `saved`, and the next launch reads what was saved
        term.keys("j")
        shown = lines(term.wait("› review_lines"))
        self.assertIn(row("rounds", 4, "default 3"), shown)
        again = self.opened()
        self.assertIn(row("rounds", 4, "default 3"), lines(again.wait("seat_lines")))

        term.keys("k", "Left")
        shown = lines(term.wait("saved"))
        self.assertIn(row("rounds", 3, "", "saved", on=True), shown)
        self.assertEqual(akconfig.read(self.home)["rounds"], 3)

    def test_seat_lines_stays_at_its_floor(self):
        term = self.c({"seat_lines": 0})
        self.to(term, "seat_lines")
        term.keys("Left", "Right")      # a step under 0 counted would leave this at 0
        shown = lines(term.wait("saved"))
        self.assertIn(row("seat_lines", 1, "default 50", "saved", SEAT, on=True), shown)
        self.assertEqual(akconfig.read(self.home)["seat_lines"], 1)
        term.keys("Left", "Left")
        term.wait(row("seat_lines", 0, "default 50", "", SEAT, on=True))     # refused: not saved
        self.assertEqual(akconfig.read(self.home)["seat_lines"], 0)

    def test_seat_lines_stops_at_review_lines_and_review_lines_at_seat_lines(self):
        term = self.c({"review_lines": 100, "seat_lines": 99})
        self.to(term, "seat_lines")
        term.keys("Right", "Right", "Left")     # a step over 100 counted would leave this at 100
        term.wait(row("seat_lines", 99, "default 50", "saved", SEAT, on=True))
        self.assertEqual(akconfig.read(self.home)["seat_lines"], 99)
        term.keys("Right", "k", "Left", "Right")
        term.wait(row("review_lines", 101, "default 300", "saved", REVIEW, on=True))
        saved = akconfig.read(self.home)
        self.assertEqual((saved["review_lines"], saved["seat_lines"]), (101, 100))

    def test_enter_and_space_do_nothing_on_a_number(self):
        term = self.c()
        self.to(term, "rounds")
        before = (self.home.path / ".agentkit/config.toml").read_text()
        term.keys("Enter", "Space", "j")
        shown = term.wait("› review_lines")
        self.assertIn("agentkit · config", lines(shown)[0])
        self.assertEqual((self.home.path / ".agentkit/config.toml").read_text(), before)

    def test_the_pointer_opens_the_line_and_a_key_while_it_is_away_steps_nothing(self):
        term = self.c()
        at = lines(term.wait("seat_lines")).index(row("rounds", 3)) + 1
        term.type(f"\x1b[<35;8;{at}M")
        term.wait(MEANS["rounds"])
        term.type("\x1b[<35;8;1M")      # onto the header: the highlight goes out, and the line
        term.wait(lambda screen: MEANS["rounds"] not in screen)
        term.keys("Right")              # only brings it back
        term.wait(MEANS["rounds"])
        self.assertNotIn("rounds", akconfig.read(self.home))

    def test_a_step_that_cannot_be_saved_changes_nothing_and_says_why(self):
        term = self.c()
        given = (self.home.path / ".agentkit/config.toml").read_bytes()
        blocked = self.home.path / ".agentkit/config.tmp"
        blocked.mkdir()
        self.addCleanup(blocked.rmdir)
        self.to(term, "rounds")
        term.keys("Right")
        self.assertIn(row("rounds", 3, on=True), lines(term.wait("Is a directory")))
        self.assertEqual((self.home.path / ".agentkit/config.toml").read_bytes(), given)

    def test_on_a_narrow_terminal_the_boards_fold_under_their_row_never_cut(self):
        shown = lines(self.c({"rounds": 4}, size=(40, 50)).wait("seat_lines"))
        at = shown.index("  rounds        4    default 3")
        self.assertEqual(shown[at + 1:at + 3],
                         ["    moves first round, unmerged, hours", "    to merge"])

    def test_a_home_file_of_top_level_keys_alone_keeps_its_numbers(self):
        path = self.home.path / ".agentkit/config.toml"
        path.write_text('rounds = 5\nreview_lines = 200\n')
        term = self.opened(size=(100, 50))     # the shipped config answers for its models
        self.assertIn(row("rounds", 5, "default 3"), lines(term.wait("seat_lines")))
        term.keys(*["j"] * 30)                 # the last row
        term.wait("› seat_lines")
        term.keys("Left")
        term.wait(row("seat_lines", 49, "default 50", "saved", SEAT, on=True))
        saved = akconfig.read(self.home)
        self.assertEqual((saved["rounds"], saved["review_lines"], saved["seat_lines"]),
                         (5, 200, 49))


if __name__ == "__main__":
    unittest.main()
