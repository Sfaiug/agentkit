"""A review whose tree lacks its chosen tests takes no lane.

The time record keeps a part while its file exists, so a reviewer's PASS can choose a part its tree
no longer holds.  Where the tree holds none of the tests chosen, their go passes nothing: the PASS
stands, as for a review that chose none, and nothing is handed again, so no green go of none opens
the looks-alone lane
(tests/test_key_the_looks_lane_takes_only_a_change_whose_chosen_tests_passed.py), and the change
lands only through the whole suite, its merge ending with `Suite-Passed-Tree: <tree>`.

Black-box, on the fixtures of that key: in a project whose time record still times a part `gone`
of `t/ok.sh`, a landing on record red on it, a change of prose alone is reviewed PASS on an idle
host (AK_HOST_READINGS), its project's runner logging the tests each go of it is handed.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_key_a_change_of_looks_alone_lands_on_its_quick_checks as quick
import test_key_the_looks_lane_takes_only_a_change_whose_chosen_tests_passed as looks

PART = "t/ok.sh::gone"
# each go handed tests names them: one line for the one part
HANDED = quick.NAMED.replace('echo "alone $*"', 'echo "alone $(cat "$AK_ONLY")"')


class AReviewWhoseTreeLacksItsChosenTestsTakesNoLane(unittest.TestCase):
    line = vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)["line"]
    deliver = looks.TheLooksLaneTakesOnlyAChangeWhoseChosenTestsPassed.deliver

    def test_a_pass_that_chose_only_a_part_its_tree_lacks_lands_through_the_whole_suite(self):
        line = self.line(times={PART: 1},
                         **{"news.md": looks.NEWS + "More news.\n", "suite.sh": HANDED})
        quick.red(line, PART)
        tree, message = self.deliver(line, quick.IDLE)
        self.assertEqual([run for run in line.runs() if run[0] == "alone"], [("alone", PART)])
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)


if __name__ == "__main__":
    unittest.main()
