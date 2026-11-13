"""A run's own scope is in the kernel's idle class from before its first round, and again after a
delivery that ends unmerged: a thread of a line's check that wakes takes its core at once.
Where the manager refuses `idle`, the scope has a run's weight and the run ends as it would have.

A weight shares CPU over time and does not decide who runs next: beside runs at weight 40 a whole
check took 84 minutes, and 43 beside none (13 Nov 2026).
Black-box, on the fixture of tests/test_key_a_delivering_run_has_the_landing_weight.py.
"""

import unittest

from test_key_a_delivering_run_has_the_landing_weight import Delivery, weight

# Notes in the test's folder that `idle` was asked before any harness took a turn.
FIRST = ('*" CPUWeight=idle "*) ls {root}/adapters/*.n >/dev/null 2>&1 || : >{root}/first; '
         'exit 0 ;; ')


class RunYieldsTheCpuToALineSCheck(Delivery, unittest.TestCase):
    # The run's process, then each resume that delivers, asks as it starts.
    def test_a_run_is_idle_before_its_first_round_and_again_after_an_unmerged_delivery(self):
        unit = self.deliver(FIRST, moved=True)["scope"]
        self.assertTrue((self.home.root / "first").exists())
        idle, top = weight(unit, "idle"), weight(unit, 10000)
        self.assertEqual(self.asked(unit), [idle, idle, top, idle, idle, top])

    def test_where_the_manager_refuses_idle_a_run_has_a_runs_weight_and_merges(self):
        unit = self.deliver('*" CPUWeight=idle "*) exit 1 ;; ', moved=True)["scope"]
        idle, run, top = weight(unit, "idle"), weight(unit, 40), weight(unit, 10000)
        self.assertEqual(self.asked(unit),
                         [idle, run, idle, run, top, idle, run, idle, run, top])
        self.assertEqual(self.warned(), [])

if __name__ == "__main__":
    unittest.main()
