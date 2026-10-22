"""`ak orch why NAME` and `ak orch list --why` say why each seat has its word.

A seat's word (`working`, `needs you`, `done`, `idle`) is all the owner sees on a row; when it
looks wrong, these two are where the reason, the rule or hook that decided it and the screen
line it read are shown, and a seat whose process is gone says nothing read its screen rather
than inventing a rule.  A name that is no seat's, or a stray argument, is refused with exit 2
and a line saying what to type instead.  A narrow terminal stacks the listing's columns under
each seat's name, so a phone reads every row whole.  Black-box: seats are tmux sessions on the
Home's own server (tests/fixtures/akseat.py), and the tests fail against `/bin/false`.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

WIDE, NARROW = {"COLUMNS": "200"}, {"COLUMNS": "40"}
ASKED = "Enter to select · ↑/↓ to navigate · Esc to cancel"
SINCE = r"  since:     \d{4}-\d{2}-\d{2} \d{2}:\d{2} \(\S+ ago\)"
SLICE = "no slice (no user systemd manager)"
WHY_SLICE = f"  slice:     {SLICE}; this seat's tmux server was started plainly"
NOTHING_MATCHED = ["  reason:    -",
                   "  authority: default  rule: none",
                   "  evidence:  no hook fact and no screen rule matched",
                   "  since:     unknown"]
GONE = "  authority: -     the process is gone; nothing here read its screen"
DAY = 86400


class Refusals(unittest.TestCase):
    """A Home with no seat at all and no tmux server running."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def refused(self, *args):
        done = self.home.ak(*args)
        self.assertEqual(done.code, 2, f"ak {' '.join(args)}: {done.out}{done.err}")
        self.assertEqual(done.out, "")
        return done.err

    def test_why_for_a_seat_that_does_not_exist_points_at_the_list(self):
        for name in ("acme", "nope"):
            with self.subTest(name=name):
                self.assertEqual(self.refused("orch", "why", name),
                                 f"ak orch: no orchestrator session '{name}'; "
                                 "`ak orch list` shows them\n")

    def test_why_takes_exactly_one_name(self):
        for args in (("orch", "why"), ("orch", "why", "acme", "beta")):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*args), "ak orch: usage: ak orch why NAME\n")

    def test_list_takes_only_one_why_flag(self):
        for args in (("orch", "list", "--bogus"), ("orch", "list", "--why", "--why"),
                     ("orch", "list", "acme"), ("orch", "list", "--why", "acme")):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*args), "ak orch: usage: ak orch list [--why]\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Explained(unittest.TestCase):
    """Three seats, numbered in the order they were made: fix-api's screen matches no rule,
    acme asks a question, and beta's tmux session is gone with only its record left."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        now = int(time.time())
        cls.seats = {
            "fix-api": Seat(cls.home, "fix-api", screen="fix-api\n\nnothing on this screen\n",
                            record={"created": now - 3 * DAY}),
            "acme": Seat(cls.home, "acme", screen="claude-question-pane.txt",
                         record={"created": now - 2 * DAY}),
            "beta": Seat(cls.home, "beta", alive=False, record={"created": now - DAY}),
        }

    def ak(self, *args, env=WIDE):
        done = self.home.ak(*args, env=env)
        self.assertEqual(done.code, 0, f"ak {' '.join(args)}: {done.err}")
        return done.out.splitlines()

    def path(self, name):
        return f"  path: {self.seats[name].cwd}"

    def test_why_says_a_screen_no_rule_reads_rests_idle_by_default(self):
        self.assertEqual(self.ak("orch", "why", "fix-api"),
                         ["fix-api  idle", *NOTHING_MATCHED, WHY_SLICE])

    def test_why_names_the_screen_rule_and_the_line_it_matched(self):
        lines = self.ak("orch", "why", "acme")
        self.assertEqual(lines[:4], ["acme  needs you", f"  reason:    {ASKED}",
                                     "  authority: screen  rule: asking.question",
                                     f"  evidence:  {ASKED}"])
        self.assertRegex(lines[4], f"^{SINCE}$")
        self.assertEqual(lines[5:], [WHY_SLICE])

    def test_why_for_a_seat_whose_process_is_gone_says_nothing_read_its_screen(self):
        self.assertEqual(self.ak("orch", "why", "beta"),
                         ["beta  idle", "  reason:    session closed: press 3 to reopen",
                          GONE, WHY_SLICE])

    def test_why_for_a_name_beside_the_seats_is_still_refused(self):
        done = self.home.ak("orch", "why", "nope", env=WIDE)
        self.assertEqual((done.code, done.out), (2, ""))
        self.assertEqual(done.err,
                         "ak orch: no orchestrator session 'nope'; `ak orch list` shows them\n")

    def test_list_why_puts_each_seats_path_and_explanation_under_its_row(self):
        lines = self.ak("orch", "list", "--why")
        blocks = {"fix-api": [self.path("fix-api"), *NOTHING_MATCHED],
                  "acme": [self.path("acme"), f"  reason:    {ASKED}",
                           "  authority: screen  rule: asking.question",
                           f"  evidence:  {ASKED}", SINCE],
                  "beta": [self.path("beta"), "  reason:    session closed: press 3 to reopen",
                           GONE]}
        self.assertEqual(lines[-1], SLICE)
        rows = [i for i, line in enumerate(lines[:-1]) if not line.startswith(" ")]
        self.assertEqual([lines[i].split()[0] for i in rows], ["name", "fix-api", "acme", "beta"])
        for at, (name, block) in zip(rows[1:], blocks.items()):
            with self.subTest(seat=name):
                under = lines[at + 1:at + 1 + len(block)]
                self.assertEqual(len(under), len(block))
                for line, want in zip(under, block):
                    if want == SINCE:
                        self.assertRegex(line, f"^{SINCE}$")
                    else:
                        self.assertEqual(line, want)
        self.assertEqual(len(lines), 1 + 3 + sum(map(len, blocks.values())) + 1)

    def test_a_narrow_terminal_stacks_each_seats_columns_under_its_name(self):
        # a live seat's age is its tmux session's, which the test does not choose
        shown = ["name     project",
                 "fix-api  no project", "  ○ idle  no runs yet  opus  AGE", "  opus",
                 "acme     no project", "  ! needs you  no runs yet  opus  AGE", "  opus",
                 "beta     no project", "  ○ idle  no runs yet  opus  1d", "  opus",
                 SLICE]
        pattern = "\n".join(re.escape(line).replace("AGE", r"\S+") for line in shown)
        self.assertRegex("\n".join(self.ak("orch", "list", env=NARROW)), f"^{pattern}$")

    def test_a_narrow_list_why_keeps_each_explanation_under_its_stacked_row(self):
        lines = self.ak("orch", "list", "--why", env=NARROW)
        at = lines.index("beta     no project")
        self.assertEqual(lines[at + 1:], ["  ○ idle  no runs yet  opus  1d", "  opus",
                                          self.path("beta"),
                                          "  reason:    session closed: press 3 to reopen",
                                          GONE, SLICE])
        at = lines.index("fix-api  no project")
        self.assertEqual(lines[at + 3:at + 8], [self.path("fix-api"), *NOTHING_MATCHED])


if __name__ == "__main__":
    unittest.main()
