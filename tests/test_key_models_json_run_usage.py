"""`ak models --json` gives what the builds and the reviews of every run took (`runs`' `usage`):
{"executor": {"points": {provider: {plan: points}}, "unrated": tokens},
 "reviewer": {"points": {provider: {plan: points}}, "unrated": tokens}}.

- A role's usage is that of the `turn_usage` rows naming a run and that role, chosen as
  `week_meters.days` chooses rows: in the window, of a turn on a harness of that provider, their
  four counts whole numbers summing above zero.  Any other row is no row.
- A row's plan is the one its login's reading last at or before the row's `at` names, else its
  first reading after; the readings are those `days` counts steps between.
- A row takes its tokens times the rate the same call's `week_meters` gives its model under that
  provider and plan; its tokens are `unrated` where it names no model, its login has no reading or
  that reading no plan, or the plan has no rate for its model.
- A role's `points` sum exactly and print to six significant digits as the rates print, a plan with
  none not named; `unrated` is whole tokens.  Both roles are always there; a history that cannot
  answer gives both none.

Black-box: tests/test_key_models_json_week_meters.py's Home, `turn_usage` holding `run_id` and
`role`; judged by the output and exit code.  Fails against /bin/false.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_json_week_meters import ENV, HOUR, TABLES as BASE, THEN, WeekMeters

TABLES = {**BASE, "turn_usage": "run_id, role, " + BASE["turn_usage"]}
EMPTY = {"executor": {"points": {}, "unrated": 0}, "reviewer": {"points": {}, "unrated": 0}}


class ModelsJsonRunUsage(WeekMeters):
    def turn(self, ago, counts, model="anvil-1", account="default", harness="echo",
             run_id="fix-api", role="executor"):
        """A worker turn's row of the login ending `ago` hours before THEN, naming `run_id` and
        `role`, its `harness` receipt naming `harness`."""
        turn = (self.home.path / f".agentkit/runs/{run_id or 'none'}/round-1"
                / f"{role or 'none'}-{len(self.rows['turn_usage'])}")
        turn.mkdir(parents=True)
        (turn / "harness").write_text(harness)
        self.rows["turn_usage"].append((run_id, role, str(turn), account, model,
                                        THEN - ago * HOUR, *counts))

    def usage(self, tables=TABLES):
        return self.answer(tables)["runs"]["usage"]

    def test_builds_and_reviews_take_their_models_rates_and_sum_exactly(self):
        # acme/Max: 10 points for 100,000 tokens of anvil-1 -> 100 points a million
        self.read(50, 10)
        self.turn(45, (60_000, None, 30_000, 10_000), run_id="fix-api", role="executor")
        self.read(40, 20)
        # brine/Plus: 10 points for 300,000 tokens of bolt-1 -> 100/3 points a million; three
        # reviews of 100,000 tokens each sum exactly to 10 (not 9.99999), plus one of 100 tokens
        # (1/300) printing to six significant digits as 10.0033
        self.read(50, 0, plan="Plus", provider="brine")
        for run_id in ("fix-api", "fix-docs", "fix-pr"):
            self.turn(45, (100_000, 0, 0, 0), model="bolt-1", harness="chime",
                      run_id=run_id, role="reviewer")
        self.read(40, 10, plan="Plus", provider="brine")
        self.turn(35, (100, 0, 0, 0), model="bolt-1", harness="chime",
                  run_id="fix-pr", role="reviewer")
        self.assertEqual(self.usage(), {
            "executor": {"points": {"acme": {"Max": 10}}, "unrated": 0},
            "reviewer": {"points": {"brine": {"Plus": 10.0033}}, "unrated": 0}})

    def test_unrated_tokens_when_no_reading_no_plan_no_model_or_no_rate(self):
        # acme/Max fits anvil-1 at 75 and anvil-2 at 0 across three UTC days (noon to noon):
        # rate 0 is rated (neither points nor unrated, and Max is not named under executor's points)
        for ago, used in ((120, 0), (96, 10), (72, 10), (48, 15)):
            self.read(ago, used)
        self.seat(100, 100_000, model="anvil-1")
        self.seat(80, 100_000, model="anvil-2")
        self.seat(50, 100_000, model="anvil-1")
        self.seat(50, 100_000, model="anvil-2")
        self.read(30, 15, plan=None)                        # later turns see a reading of no plan
        self.turn(40, (50_000, 0, 0, 0), model="anvil-2")   # rate 0: rated, zero points
        self.turn(40, (1_000, 0, 0, 0), account="second")   # login with no reading
        self.turn(25, (2_000, 0, 0, 0))                     # reading names no plan
        self.turn(40, (3_000, 0, 0, 0), model=None)         # names no model
        self.turn(40, (4_000, 0, 0, 0), model="")           # blank model
        self.turn(40, (5_000, 0, 0, 0), model="anvil-9")    # model with no rate on Max
        # brine/Plus: two models in one day alone -> rates is {}, so bolt-1 has no rate
        self.read(50, 0, plan="Plus", provider="brine")
        self.seat(45, 50_000, model="bolt-1", harness="chime")
        self.seat(45, 50_000, model="bolt-2", harness="chime")
        self.read(40, 10, plan="Plus", provider="brine")
        self.turn(35, (6_000, 0, 0, 0), model="bolt-1", harness="chime", role="reviewer")
        want = {"executor": {"points": {}, "unrated": 15_000},
                "reviewer": {"points": {}, "unrated": 6_000}}
        self.assertEqual(self.usage(), want)
        # brine absent from the usage cache (no readable shared week): its tokens stay unrated
        cache = self.home.path / ".agentkit/state/usage.json"
        cached = json.loads(cache.read_text())
        del cached["providers"]["brine"]
        cache.write_text(json.dumps(cached))
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(json.loads(done.out)["runs"]["usage"], want)

    def test_a_login_that_changed_plan_values_each_row_under_the_plan_of_its_time(self):
        # Pro: 100 pts/M (70 -> 60); Max: 20 pts/M (40 -> 30); scoped reading at 55 is no reading
        self.read(70, 0, plan="Pro")
        self.seat(65, 100_000)
        self.read(60, 10, plan="Pro")
        self.read(55, 80, plan="Max", scope="anvil")
        self.read(40, 0, plan="Max")
        self.seat(35, 100_000)
        self.read(30, 2, plan="Max")
        self.turn(80, (100_000, 0, 0, 0))   # before first reading -> first after (Pro: 10)
        self.turn(50, (100_000, 0, 0, 0))   # between Pro and Max, past scoped -> last before (Pro: 10)
        self.turn(40, (100_000, 0, 0, 0))   # at Max reading -> Max (2)
        self.turn(20, (100_000, 0, 0, 0))   # after last reading -> last before (Max: 2)
        self.assertEqual(self.usage(), {
            "executor": {"points": {"acme": {"Pro": 20, "Max": 4}}, "unrated": 0},
            "reviewer": {"points": {}, "unrated": 0}})

    def test_rows_naming_no_run_or_not_counted_by_days_count_nowhere(self):
        self.read(50, 0)
        self.seat(45, 100_000)
        self.read(40, 10)
        # turns after the fitting step so their tokens never alter the fitted 100 pts/M rate
        self.turn(35, (100_000, 0, 0, 0), run_id=None)
        self.turn(35, (100_000, 0, 0, 0), run_id="")
        self.turn(35, (100_000, 0, 0, 0), role=None)
        self.turn(35, (100_000, 0, 0, 0), role="other")
        self.turn(35, (0, 0, 0, 0))
        self.turn(35, ("500", 0, 0, 0))
        self.turn(35, (100_000, 0, 0, 0))
        Path(self.rows["turn_usage"][-1][2], "harness").write_bytes(b"\xff")
        self.turn(40 * 24, (100_000, 0, 0, 0))              # outside the 30-day window
        self.turn(35, (10_000, 0, 0, 0))                    # the one counted row: 1 point
        self.assertEqual(self.usage(), {
            "executor": {"points": {"acme": {"Max": 1}}, "unrated": 0},
            "reviewer": {"points": {}, "unrated": 0}})

    def test_a_history_that_cannot_answer_gives_both_roles_none(self):
        self.read(50, 0)
        self.read(40, 10)
        self.turn(45, (100_000, 0, 0, 0))
        # meter_readings without plan, as before plans were kept
        self.rows["meter_readings"] = [row[:-2] for row in self.rows["meter_readings"]]
        self.assertEqual(self.usage({**TABLES, "meter_readings": (
            "provider, account, meter, used, resets_at, window_secs, at, source, "
            "PRIMARY KEY (provider, account, meter, at)")}), EMPTY)

    def test_a_login_no_longer_configured_values_its_builds_under_its_plan(self):
        # removed acme login: 10 points for 100,000 tokens -> 100 pts/M; both builds rated
        self.read(50, 10, account="removed")
        self.turn(45, (100_000, 0, 0, 0), account="removed", run_id="fix-api", role="executor")
        self.read(40, 20, account="removed")
        self.turn(35, (50_000, 0, 0, 0), account="removed", run_id="fix-docs", role="executor")
        self.assertEqual(self.usage(), {
            "executor": {"points": {"acme": {"Max": 15}}, "unrated": 0},
            "reviewer": {"points": {}, "unrated": 0}})


if __name__ == "__main__":
    unittest.main()
