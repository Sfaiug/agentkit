"""A follow-up's check is its proof without the `timeout N` its reviewer began it with: on a
loaded host a right fix ran past that bound and its fix run ended blocked, while a plan line
and a fix run's done-when each have a bound of ak's own.  A proof that ended in 124, the bound
itself failing, keeps it.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import hand_in

CHECK = "tools/test.sh tests/test_api.py::test_cleanup -q"


def check(run, returncode):
    """The check ak takes from a follow-up proven by `run` ending in `returncode`."""
    row = {"kind": "follow-up", "path": "api.py", "line": 2, "what": "expired rows stay",
           "why": "cleanup lags", "evidence": {"run": run, "returncode": returncode, "output": ""}}
    return list(hand_in.Review([row, {"kind": "done"}]).followup_checks.values())


class FollowUpCheckWithoutItsReviewersBound(unittest.TestCase):
    def test_the_bound_its_reviewer_began_the_proof_with_leaves(self):
        self.assertEqual(check("timeout 120 " + CHECK, 1), [CHECK])
        self.assertEqual(check("timeout 15s " + CHECK, 1), [CHECK])

    def test_a_bound_that_is_what_fails_stays(self):
        self.assertEqual(check("timeout 20 " + CHECK, 124), ["timeout 20 " + CHECK])


if __name__ == "__main__":
    sys.exit(unittest.main())
