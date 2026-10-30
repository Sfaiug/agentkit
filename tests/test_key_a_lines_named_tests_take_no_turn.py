"""A line narrowing a red to the tests it named runs them at once, taking no heavy turn on this host;
a piece it has to run whole still waits for one."""

import unittest

import test_the_log_says_where_a_suite_ran as fixture


class ALinesNamedTestsTakeNoTurn(unittest.TestCase):
    setUp, check, turn = fixture.SuiteLocation.setUp, fixture.SuiteLocation.check, fixture.SuiteLocation.turn

    def test_named_tests_take_none_and_a_whole_piece_one(self):
        self.check('echo tests/test_a.py >>"$AK_RAN"', shard="2/3", only=["tests/test_a.py"])
        self.assertEqual(self.turns, [])
        self.check(shard="2/3")
        self.assertTrue(self.turns)


if __name__ == "__main__":
    unittest.main()
