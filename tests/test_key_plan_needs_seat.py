"""`ak plan` belongs to a seat, and `ak plan add` to a seat filed under a project.

A plan line is the seat's promise, checked on its project's default branch, so a plan with no
seat to own it or no project to check it on is refused before anything is written, with the
next step named.  A model reads that refusal and acts on it, so its words are pinned.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat

OUTSIDE = "ak plan: ak plan belongs to a session; run it inside one\n"
NO_PROJECT = ("ak plan: {} is filed under no project; "
              "run `ak orch project <checkout>` first\n")
FORMS = (("plan",), ("plan", "add", "x", "--check", "false"), ("plan", "check", "1", "true"))


class PlanNeedsSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def plans(self):
        return sorted(self.home.path.joinpath(".agentkit").rglob("plan-*"))

    def test_every_form_of_ak_plan_outside_a_seat_is_refused(self):
        # an empty seat variable is no seat either
        for env in ({}, {"AGENTKIT_SESSION": ""}):
            for args in FORMS:
                with self.subTest(env=env, args=args):
                    done = self.home.ak(*args, env=env)
                    self.assertEqual(done.code, 2, done.out)
                    self.assertEqual(done.err, OUTSIDE)
        self.assertEqual(self.plans(), [])

    def test_adding_a_line_in_a_seat_filed_under_no_project_points_at_ak_orch_project(self):
        Seat(self.home, "fix-api", alive=False)
        done = self.home.ak("plan", "add", "the parser works",
                            "--check", "python3 tests/test_parser.py",
                            env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, NO_PROJECT.format("fix-api"))
        self.assertEqual(self.plans(), [])

    def test_a_project_that_is_not_a_checkout_is_no_project(self):
        plain = self.home.path / "code" / "acme"
        plain.mkdir(parents=True, exist_ok=True)
        Seat(self.home, "beta", record={"repo": str(plain)}, alive=False)
        done = self.home.ak("plan", "add", "the parser works", "--check", "true",
                            env={"AGENTKIT_SESSION": "beta"})
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, NO_PROJECT.format("beta"))
        self.assertEqual(self.plans(), [])


if __name__ == "__main__":
    unittest.main()
