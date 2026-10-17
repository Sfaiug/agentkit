"""The scoreboard names a week's largest loss against the vision: the first measure, in the
vision's order (quality, then speed, then cost, then size), that reads worse than the week
before, else the first the board reads at all this week, and none off an empty board.  Each
value prints as its kind reads: a share as a percentage, hours to a tenth, a count whole.

Offline: boards built by hand, no history and no git.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import scoreboard

STATS = {"runs": 10, "merged": 6, "first_round": .5, "unmerged": .3, "hours": 1.0, "tokens": 1000}
BOARD = {
    "products": [STATS, {**STATS, "runs": 8, "merged": 5, "first_round": .6, "unmerged": .2,
                         "hours": 2.0, "tokens": 900}],
    "ak": [None, None], "waits": [None, None], "merged": [None, None],
    "escaped": [{"merged": 6, "escaped": 3, "open": 0, "unknown": 0, "reviewers": {}},
                {"merged": 5, "escaped": 3, "open": 0, "unknown": 0, "reviewers": {}}],
    "size": [None, None],
}
EMPTY = {key: [None, None] for key in BOARD}
REWRITTEN = "merged changes with a line rewritten within 7 days"


class Loss(unittest.TestCase):
    def test_the_first_measure_in_the_vision_s_order_that_got_worse(self):
        # quality first: the rewritten share fell, so the next quality measure that rose names it
        self.assertEqual(scoreboard.loss(BOARD), ("product runs ended without merging", .3, .2, "%"))
        worse = {**BOARD, "escaped": [BOARD["escaped"][0], {**BOARD["escaped"][1], "escaped": 2}]}
        self.assertEqual(scoreboard.loss(worse), (REWRITTEN, .5, .4, "%"))
        # less merged in round 1 is worse, though the number fell
        fewer = {**BOARD, "products": [STATS, {**STATS, "first_round": .6}]}
        self.assertEqual(scoreboard.loss(fewer), ("product runs merged in round 1", .5, .6, "%"))
        # speed after quality: with every quality measure as good or better, the hours name it
        slower = {**BOARD, "products": [{**STATS, "hours": 3.0}, {**STATS, "hours": 2.0}],
                  "escaped": [BOARD["escaped"][0], BOARD["escaped"][0]]}
        self.assertEqual(scoreboard.loss(slower), ("hours to merge a product run", 3.0, 2.0, "h"))
        # the owner's own wait is the first speed: slower from their first message to done names
        # it ahead of the hours to merge
        waited = {**slower, "intent": [{"measured": 2, "hours": 5.0}, {"measured": 2, "hours": 4.0}]}
        self.assertEqual(scoreboard.loss(waited), ("hours from the owner's first message to done", 5.0, 4.0, "h"))
        # a week four times faster and cheaper with one quality measure a shade worse is a loss
        # on that quality measure, whatever the speed: the order is the owner's (14 Oct)
        faster_but_worse = {**BOARD, "products": [{**STATS, "unmerged": .31, "hours": .5, "tokens": 200},
                                                  {**STATS, "unmerged": .3, "hours": 2.0, "tokens": 900}],
                            "escaped": [BOARD["escaped"][0], BOARD["escaped"][0]]}
        self.assertEqual(scoreboard.loss(faster_but_worse),
                         ("product runs ended without merging", .31, .3, "%"))
        # and cost after speed, size last: everything better but the lines of code names those
        bigger = {**BOARD, "products": [STATS, {**STATS, "unmerged": .4, "hours": 2.0, "tokens": 2000}],
                  "escaped": [BOARD["escaped"][0], BOARD["escaped"][0]],
                  "size": [{"code_lines": 110, "readme_words": 9, "agents_words": 9},
                           {"code_lines": 100, "readme_words": 9, "agents_words": 9}]}
        self.assertEqual(scoreboard.loss(bigger), ("ak's code lines", 110, 100, "n"))
        # the owner's time is the first cost, ahead of tokens; tokens that bought no merge ahead
        # of the park
        asked = {**bigger, "owner": [{"asked": 3, "paged": 1, "hours": 9.0}, {"asked": 2, "paged": 1, "hours": 1.0}]}
        self.assertEqual(scoreboard.loss(asked), ("questions asked of the owner", 3, 2, "n"))
        paged = {**bigger, "owner": [{"asked": 2, "paged": 4, "hours": None}, {"asked": 2, "paged": 1, "hours": None}]}
        self.assertEqual(scoreboard.loss(paged), ("cards sent to the owner", 4, 1, "n"))
        sunk = {**bigger, "sunk": [{"share": .4, "tokens": 9}, {"share": .1, "tokens": 9}],
                "parks": [{"parked": 3}, {"parked": 0}]}
        self.assertEqual(scoreboard.loss(sunk), ("tokens spent on runs that never merged", .4, .1, "%"))

    def test_nothing_worse_names_the_first_measure_the_board_reads_at_all(self):
        same = {**BOARD, "products": [STATS, STATS]}
        self.assertEqual(scoreboard.loss(same), (REWRITTEN, .5, .6, "%"))
        only_size = {**EMPTY, "size": [{"code_lines": 100, "readme_words": 9, "agents_words": 9}, None]}
        self.assertEqual(scoreboard.loss(only_size), ("ak's code lines", 100, None, "n"))
        # a row a newer board adds is read once it is there, and read as none before
        self.assertEqual(scoreboard.loss({**EMPTY, "parks": [{"parked": 2}, {"parked": 0}]}),
                         ("runs the park stopped", 2, 0, "n"))
        self.assertIsNone(scoreboard.loss(EMPTY))
        self.assertIsNone(scoreboard.loss({}))

    def test_a_share_of_nothing_merged_reads_as_none(self):
        none_merged = {**EMPTY, "escaped": [{"merged": 0, "escaped": 0, "open": 0, "unknown": 0,
                                              "reviewers": {}}, None]}
        self.assertIsNone(scoreboard.loss(none_merged))

    def test_each_value_prints_as_its_kind_reads(self):
        self.assertEqual((scoreboard.said(.3, "%"), scoreboard.said(1.25, "h"),
                          scoreboard.said(1234.0, "n"), scoreboard.said(None, "n")),
                         ("30%", "1.2 hours", "1,234", "not recorded"))


if __name__ == "__main__":
    unittest.main()
