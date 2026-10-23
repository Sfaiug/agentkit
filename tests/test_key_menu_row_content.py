"""The menu's seat rows: a seat tmux lost, a plan's bar, and a done seat `x` closes at once.

A row is all the owner reads of a seat before opening it.  A seat whose tmux session went keeps
its row, `idle`, or `needs you` while its plan owes a line, and says how its number reopens it;
a seat with a plan shows how much of it is done, counted as the stop hook counts it, so the bar
never claims work nothing proved; and a done seat closes on `x` without a question, as nothing
in it is left to lose.  Black-box: the program `AK_BIN` names runs in a person's terminal
(tests/fixtures/akterm.py) or from a pipe, beside tests/fixtures/akseat.py's seats, and this
test fails against `/bin/false`.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

SIZE = (100, 30)
OPENS = 60      # the first draw looks at every seat, which a loaded host makes slow
REOPEN = "     session closed: press"     # under the row, at the name's column
BAR = re.compile(r" (?P<full>━*)(?P<half>╸?)(?P<rest>─*) (?P<done>\d+) of (?P<total>\d+)$")


def checked(mark, what, done=None):
    """A plan line as `ak plan` writes it, ticked on a commit where `done` names one."""
    return (f"- [{mark}] {what} · check: `true` · atoll · written 2026-10-02 12:40"
            + (f" · done {done}" if done else ""))


def seats(home, *specs):
    """Seats under ~/code/atoll, (name, screen or None for one tmux lost, plan lines), made a
    minute apart in the order given, which is the order their numbers go."""
    made = int(time.time()) - 3600
    for at, (name, screen, plan) in enumerate(specs):
        Seat(home, name, model="fable", cwd=home.path / "code" / "atoll",
             screen=screen or "claude-prompt-pane.txt", alive=screen is not None,
             record={"created": made + 60 * at})
        if plan:
            home.write(f".agentkit/state/plan-{name}.md", "\n".join(plan) + "\n")


def row(screen, name):
    """A seat's row and the line under it, each without its trailing blanks."""
    lines = [line.rstrip() for line in screen.splitlines()] + [""]
    at = next((n for n, line in enumerate(lines)
               if re.match(rf"[› ] \d+  {re.escape(name)} ", line)), None)
    assert at is not None, f"no row for {name}:\n{screen}"
    return lines[at], lines[at + 1]


def shows(*rows):
    """A test of a screen: each (name, pattern) seat's row matches its pattern.  A seat is
    drawn as last recorded before it is looked at, so the first frames may say otherwise."""
    def test(screen):
        lines = [line.rstrip() for line in screen.splitlines()]
        return "esc leave" in screen and all(
            any(re.match(rf"[› ] \d+  {re.escape(name)} +{pattern}", line) for line in lines)
            for name, pattern in rows)
    return test


def key_line(screen):
    return next(line.strip() for line in screen.splitlines() if "esc leave" in line)


def gone(home, name, bound=30):
    """Whether tmux has no session `name` within `bound` seconds."""
    deadline = time.monotonic() + bound
    while home.tmux("has-session", "-t", f"={name}").code == 0:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatsTmuxLost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        seats(cls.home, ("ghost-a", None, []), ("ghost-b", None, [checked(" ", "x")]))

    def test_a_lost_seat_says_how_to_reopen_it_once_the_highlight_moves_onto_it(self):
        menu = Terminal(self.home, size=SIZE)
        screen = menu.wait(shows(("ghost-a", "Fable 5.1  ○ idle"),
                                 ("ghost-b", "Fable 5.1  ! needs you")), bound=OPENS)
        self.assertEqual(row(screen, "ghost-a")[0], "› 1  ghost-a  Fable 5.1  ○ idle")
        self.assertTrue(row(screen, "ghost-b")[0].startswith(
            "  2  ghost-b  Fable 5.1  ! needs you"))
        self.assertNotIn("session closed", screen)    # nobody has pointed at a row yet
        menu.keys("j")
        screen = menu.wait("press 2 to reopen")
        ghost_b = row(screen, "ghost-b")
        self.assertTrue(ghost_b[0].startswith("› 2  ghost-b"), screen)
        self.assertEqual(ghost_b[1], f"{REOPEN} 2 to reopen")
        menu.keys("k")
        screen = menu.wait("press 1 to reopen")
        self.assertEqual(row(screen, "ghost-a"),
                         ("› 1  ghost-a  Fable 5.1  ○ idle", f"{REOPEN} 1 to reopen"))
        self.assertNotIn("press 2 to reopen", screen)
        menu.keys("Escape")
        self.assertEqual(menu.exit_code(), 0)

    def test_from_a_pipe_every_lost_seat_says_how_to_reopen_it(self):
        done = self.home.ak(input="\n")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(row(done.out, "ghost-a"),
                         ("  1  ghost-a  Fable 5.1  ○ idle", f"{REOPEN} 1 to reopen"))
        ghost_b = row(done.out, "ghost-b")
        self.assertTrue(ghost_b[0].startswith("  2  ghost-b  Fable 5.1  ! needs you"), done.out)
        self.assertEqual(ghost_b[1], f"{REOPEN} 2 to reopen")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PlanBars(unittest.TestCase):
    """Done is a line ticked on the commit its check passed on, or one kept by hand with none of
    the fields `ak plan` writes; a line ticked past its proof is open, and one with no box is no
    line of the plan."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        seats(cls.home,
              ("atoll-fix", "claude-working-pane.txt",
               ["# atoll", *(checked("x", f"part {n}", "abc1234") for n in range(3)),
                checked("x", "ticked past its proof"),
                *(checked(" ", f"next {n}") for n in range(3))]),
              ("atoll-job", "claude-working-pane.txt",
               ["- [x] tidy the readme", checked(" ", "ship it")]),
              ("atoll-ask", "claude-question-pane.txt", []))
        menu = Terminal(cls.home, size=SIZE)
        cls.screen = menu.wait(shows(("atoll-fix", "Fable 5.1  ● working .* 3 of 7$"),
                                     ("atoll-job", "Fable 5.1  ● working .* 1 of 2$"),
                                     ("atoll-ask", "Fable 5.1  ! needs you$")), bound=OPENS)

    def assertShare(self, line, done, total):
        bar = BAR.search(line)
        self.assertIsNotNone(bar, line)
        self.assertEqual((int(bar["done"]), int(bar["total"])), (done, total), line)
        cells = len(bar["full"]) + len(bar["half"]) + len(bar["rest"])
        # a half cell `╸` where the share ends inside one: the line is right to half a cell
        halves = 2 * len(bar["full"]) + len(bar["half"])
        self.assertLessEqual(abs(halves - 2 * cells * done / total), 1, line)

    def test_the_bar_counts_only_lines_ticked_on_a_commit(self):
        fix = row(self.screen, "atoll-fix")[0]
        self.assertIn("● working", fix)
        self.assertShare(fix, 3, 7)

    def test_a_line_kept_by_hand_counts_done_once_ticked(self):
        self.assertShare(row(self.screen, "atoll-job")[0], 1, 2)

    def test_every_bar_starts_and_ends_in_one_column_and_a_seat_with_no_plan_has_none(self):
        bars = [row(self.screen, name)[0] for name in ("atoll-fix", "atoll-job")]
        self.assertEqual(len({BAR.search(line).start() for line in bars}), 1, bars)
        self.assertEqual(len({len(line) for line in bars}), 1, bars)
        ask = row(self.screen, "atoll-ask")[0]
        self.assertTrue(ask.endswith("! needs you"), ask)
        self.assertNotRegex(ask, r"[━╸─]|\d+ of \d+")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class DoneSeat(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        seats(self.home,
              ("atoll-done", "claude-prompt-pane.txt",
               [checked("x", f"part {n}", "abc1234") for n in range(2)]),
              ("atoll-ask", "claude-question-pane.txt", []))
        self.menu = Terminal(self.home, size=SIZE)
        self.screen = self.menu.wait(shows(("atoll-done", "Fable 5.1  ✓ done .* 2 of 2$"),
                                           ("atoll-ask", "Fable 5.1  ! needs you$")), bound=OPENS)

    def test_a_seat_whose_plan_is_all_done_reads_done_with_a_full_bar_and_offers_x_close(self):
        self.assertRegex(row(self.screen, "atoll-done")[0],
                         r"^› 1  atoll-done  Fable 5.1  ✓ done +━+ 2 of 2$")
        keys = key_line(self.screen)
        self.assertIn("x close", keys)
        self.assertNotIn("x stop", keys)

    def test_x_closes_a_done_seat_at_once_without_asking(self):
        self.menu.keys("x")
        # A question would hold the row until it was answered.
        settled = shows(("atoll-ask", "Fable 5.1  ! needs you$"))
        # the row goes at once, and the seat behind it a moment later, the rows numbered again
        screen = self.menu.wait(lambda shown: "atoll-done" not in shown and settled(shown)
                                and "› 1  atoll-ask" in shown)
        self.assertTrue(gone(self.home, "atoll-done"))
        self.assertNotIn("Stop", screen)
        self.assertEqual(row(screen, "atoll-ask")[0], "› 1  atoll-ask  Fable 5.1  ! needs you")
        keys = key_line(screen)
        self.assertIn("p past", keys)       # the closed seat waits on the past screen
        self.assertIn("x stop", keys)       # the seat highlighted now is not done


if __name__ == "__main__":
    unittest.main()
