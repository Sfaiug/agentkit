"""A lander's pass ends with no verdict for anyone on a green delivery whose saved review is
gone, as an older ak erased it in the line (17 Nov 2026): the stacks behind a delivery start from
the commit its review names, and the read of a review that was not there ended every pass in a
traceback.  The delivery's own resume takes it out of the line, and the next pass checks the run
behind it.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, whose woken resumes refuse at once: the test takes the delivery out of
the line as its resume does (`transitions.leaves_line`).
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line


def rewrite(directory, change):
    path = directory / "run.json"
    state = json.loads(path.read_text())
    change(state)
    path.write_text(json.dumps(state))


class ALandersPassEndsQuietlyOnADeliveryWithNoReview(unittest.TestCase):
    def test_the_pass_ends_quietly_and_the_run_behind_is_checked_once_the_delivery_resumed(self):
        line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1))
        line.member({"web.txt": "y\n"})
        # how an older ak left a green member whose PASS it threw away: the review pending
        rewrite(line.members[0], lambda state: state.update(
            verdict=None, review=None, review_pending={"round": 4, "summary": "built"}))
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual({"land", "fix"} & line.verdict(2).keys(), set())
        rewrite(line.members[0], lambda state: state.pop("waiting_on"))
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(2))


if __name__ == "__main__":
    unittest.main()
