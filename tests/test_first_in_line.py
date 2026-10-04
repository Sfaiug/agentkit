"""A last-joined loop repair leads its landing line; ordinary members stay in join order.

Offline: real Git and checks, fake wakes, and delivery into a local bare repository.
"""

from types import SimpleNamespace
import unittest
from unittest.mock import ANY, patch

from test_lander import LanderFixture
from agentkit import land, record, run


class FirstInLine(LanderFixture, unittest.TestCase):
    def test_last_joined_first_member_is_checked_and_lands_first(self):
        earlier = self.member("z-earlier", joined=10, **{"earlier.txt": "earlier\n"})
        later = self.member("a-later", joined=20, **{"later.txt": "later\n"})
        first = self.member("repair", joined=30, **{"repair.txt": "repair\n"})
        with record.record(first) as state:
            state["first"] = True
        self.advance()
        order = [first, earlier, later]
        landed = []
        with patch.object(land, "_check_members", wraps=land._check_members) as checked:
            for index, directory in enumerate(order):
                self.wake.reset_mock()
                land.check_line(self.turn)
                self.assertEqual([member for member, _ in checked.call_args.args[1]],
                                 order[index:])
                self.wake.assert_called_once_with(directory.name, ANY)
                for waiting in order[index + 1:]:
                    self.assertNotIn("land", self.wait(waiting))
                state = record.read_state(directory)
                tree = state["waiting_on"]["land"]
                self.assertIsNotNone(land.passed(self.turn, tree))
                run.git(self.repo, "checkout", state["branch"])
                lp = SimpleNamespace(
                    state=state, wt=self.repo, run_dir=directory,
                    base_sha=state["base_sha"], target=state["target"], log=lambda _: None,
                    write=lambda: record.save_state(directory, state))

                def deliver():
                    run.git(self.remote, "fetch", "--no-tags", str(self.repo),
                            "HEAD:refs/heads/main")
                    state.update(state="pass", merged=True)
                    landed.append(directory)
                    return True

                self.assertTrue(run.land_from_line(lp, "origin/main", deliver))
                saved = record.read_state(directory)
                self.assertTrue(saved["merged"])
                self.assertNotIn("waiting_on", saved)
                self.assertEqual(saved["final_check"]["tree_sha"], tree)
        self.assertEqual([call.args[1][0][0] for call in checked.call_args_list], order)
        self.assertEqual(landed, order)
        self.assertEqual(land.line(self.turn), [])
        self.assert_cleaned()


    def test_a_green_delivery_stays_ahead_of_a_first_member(self):
        ordinary = self.member("ordinary", joined=5, **{"ordinary.txt": "ordinary\n"})
        first = self.member("repair", joined=20, **{"repair.txt": "repair\n"})
        green = self.member("green", joined=30, **{"green.txt": "green\n"})
        with record.record(first) as state:
            state["first"] = True
        with record.record(green) as state:
            state["waiting_on"] = {**state["waiting_on"], "land": "tree"}
        self.assertEqual([directory for directory, _ in land.line(self.turn)],
                         [green, first, ordinary])

if __name__ == "__main__":
    unittest.main(verbosity=2)
