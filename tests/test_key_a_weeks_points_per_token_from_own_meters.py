"""`ak models --json` names, beside each plan's `week_meters` points and tokens, `rates`: {model:
the points of the week a million of its tokens take}, one a model whatever the kind of token,
fitted from the plan's own meters and no price.

- The rates are fitted on the plan's days, one a login, plan and day, as `week_meters` sums them:
  they are the rates, none below zero, with the least sum over the days of the squared difference
  between a day's points and what its tokens take at them, so a day with no token changes none.
- The fit is exact, so no tolerance decides it, and each rate is printed to six significant digits.
- Where the days cannot tell the plan's models apart, their token counts by model linearly
  dependent, `rates` is `{}`; a model the fit gives nothing is listed at 0.

Black-box: tests/test_key_models_json_week_meters.py's Home, each login's days written as probe
readings of its week at noon UTC, a day apart, and its seat's rows between them; judged by the
output.  Fails against /bin/false.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_json_week_meters import WeekMeters


class AWeeksPointsPerTokenFromOwnMeters(WeekMeters):
    def days(self, *days, account="default"):
        """The login's `days`, (points, {model: tokens}) each, ending on the day before THEN's:
        a reading at the noon each day ends and one a day before the first, rising by the day's
        points, and a row of each model's tokens an hour before the day's reading."""
        used = 0
        self.read(24 * len(days), used, account=account)
        for ago, (points, tokens) in zip(range(24 * len(days) - 24, -1, -24), days):
            for model, count in tokens.items():
                self.seat(ago + 1, count, model=model, account=account)
            used += points
            self.read(ago, used, account=account)

    def rates(self):
        return {plan: found["rates"] for plan, found in self.week_meters()["acme"].items()}

    def test_a_plan_with_one_model_takes_its_points_over_its_tokens(self):
        self.days((10, {"anvil-1": 100_000}))
        self.assertEqual(self.rates(), {"Max": {"anvil-1": 100}})

    def test_two_logins_each_running_one_model_alone_give_each_its_own_rate(self):
        self.days((10, {"anvil-1": 100_000}))
        self.days((5, {"anvil-2": 200_000}), account="second")
        self.assertEqual(self.rates(), {"Max": {"anvil-1": 100, "anvil-2": 25}})

    def test_tokens_a_few_apart_are_told_apart_exactly(self):
        self.days((20, {"anvil-1": 999_996, "anvil-2": 1_000_004}))
        self.days((20, {"anvil-1": 1_000_004, "anvil-2": 999_996}), account="second")
        self.assertEqual(self.rates(), {"Max": {"anvil-1": 10, "anvil-2": 10}})

    def test_a_model_whose_tokens_never_moved_the_meter_takes_nothing(self):
        # anvil-2 alone rose nothing, and beside anvil-1 less than anvil-1 alone: the best fit at
        # any rate would give it one below zero, so it takes 0 and anvil-1 fits its two days
        self.days((10, {"anvil-1": 100_000}), (0, {"anvil-2": 100_000}),
                  (5, {"anvil-1": 100_000, "anvil-2": 100_000}))
        self.assertEqual(self.rates(), {"Max": {"anvil-1": 75, "anvil-2": 0}})

    def test_a_day_with_no_token_changes_no_rate(self):
        self.days((10, {"anvil-1": 100_000}))
        self.days((100, {}), account="second")
        self.assertEqual(self.rates(), {"Max": {"anvil-1": 100}})

    def test_models_that_only_ever_ran_in_one_day_together_have_no_rates(self):
        self.days((10, {"anvil-1": 100_000, "anvil-2": 50_000}))
        self.assertEqual(self.rates(), {"Max": {}})


if __name__ == "__main__":
    unittest.main()
