"""`ak models --json` counts each orchestrator's own turns and done checks of the last 30 days
(`runs.seats`): each entry, an orchestrator at an effort, holds its `seat_turns` that ended in
the window (`turns`), the median of their seconds (`turn_seconds`, null with none), its
`done_checks` (`checks`) and the asks they found missing summed (`gaps`).  An orchestrator and
effort with turns or done checks and no usage has an entry too, its `points` empty and `unrated`
0, after every entry of usage, by name and effort, null last; a turn or check naming no effort
counts in the entry of no name and no effort, where a team of no effort finds its seats' usage.

Black-box: tests/test_key_models_json_run_usage.py's Home, `seat_turns` and `done_checks` written
into its history.db as ak keeps them; judged by the output and exit code.  Fails against
/bin/false.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_json_week_meters import HOUR, THEN, WeekMeters
import test_key_models_json_run_usage as run_usage

TABLES = {**run_usage.TABLES,
          "seat_turns": "event, repo, at, seconds, account, orchestrator, effort",
          "done_checks": "session, model, effort, at, gaps"}
OUTSIDE = 40 * 24       # hours before THEN: before the window


class ModelsJsonCountsTurnsAndDoneChecks(WeekMeters):
    seat = run_usage.ModelsJsonRunUsage.seat

    def setUp(self):
        super().setUp()
        self.rows.update(seat_turns=[], done_checks=[])
        self.seat(35, 1_000, model=None, orchestrator="vega", effort="high")   # 1,000 unrated

    def own_turn(self, ago, seconds, orchestrator="vega", effort="high"):
        """A seat's turn of `orchestrator` at `effort` that took `seconds`, ending `ago` hours
        before THEN."""
        rows = self.rows["seat_turns"]
        rows.append((f"echo:turn-{len(rows)}", "acme", THEN - ago * HOUR, seconds, "default",
                     orchestrator, effort))

    def check(self, ago, gaps, model="vega", effort="high"):
        """A done check of a seat orchestrated by `model` at `effort` that found `gaps`, ending
        `ago` hours before THEN."""
        self.rows["done_checks"].append(("acme", model, effort, THEN - ago * HOUR, gaps))

    def seats(self):
        return self.answer(TABLES)["runs"]["seats"]

    def test_turns_count_and_take_the_median_of_their_seconds(self):
        for seconds in (10, 500, 30):
            self.own_turn(30, seconds)
        self.own_turn(OUTSIDE, 5)
        self.assertEqual(self.seats(), [
            {"name": "vega", "effort": "high", "points": {}, "unrated": 1_000,
             "turns": 3, "turn_seconds": 30, "checks": 0, "gaps": 0}])

    def test_done_checks_count_and_sum_their_gaps(self):
        self.check(30, 0)
        self.check(30, 3)
        self.check(OUTSIDE, 5)
        self.assertEqual(self.seats(), [
            {"name": "vega", "effort": "high", "points": {}, "unrated": 1_000,
             "turns": 0, "turn_seconds": None, "checks": 2, "gaps": 3}])

    def test_an_orchestrator_with_turns_and_no_usage_has_an_entry_after_those_with_usage(self):
        self.own_turn(30, 60, orchestrator="alto", effort="low")
        self.check(30, 2, effort=None)          # vega's, of no effort
        self.assertEqual(self.seats(), [
            {"name": "vega", "effort": "high", "points": {}, "unrated": 1_000, **run_usage.IDLE},
            {"name": "alto", "effort": "low", "points": {}, "unrated": 0,
             "turns": 1, "turn_seconds": 60, "checks": 0, "gaps": 0},
            {"name": None, "effort": None, "points": {}, "unrated": 0,
             "turns": 0, "turn_seconds": None, "checks": 1, "gaps": 2}])


if __name__ == "__main__":
    unittest.main()
