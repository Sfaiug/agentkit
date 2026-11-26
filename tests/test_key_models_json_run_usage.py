"""`ak models --json` gives what the builds and the reviews of every run and the seats' own turns
took (`runs`' `usage` and `seats`):
{"executor": {"points": {provider: {plan: points}}, "unrated": tokens},
 "reviewer": {"points": {provider: {plan: points}}, "unrated": tokens},
 "orchestrator": {"points": {provider: {plan: points}}, "unrated": tokens}}
and [{"name", "effort", "points": {provider: {plan: points}}, "unrated": tokens}].

- A build or review role's usage is that of the `turn_usage` rows naming a run and that role,
  chosen as `week_meters.days` chooses rows: in the window, of a turn on a harness of that
  provider, their four counts whole numbers summing above zero.  Any other row is no row.
- `seats` holds one entry per `orchestrator` and `effort` the counted `seat_usage` rows hold
  (chosen as `week_meters.days` chooses seat rows: in the window, `tokens` a whole number above
  zero, its event's harness of a configured provider), each a text or null as kept, most points
  first (all plans summed), then name and effort, null last; `usage.orchestrator` is their sum.
- A row's plan is the one its login's reading last at or before the row's `at` names, else its
  first reading after; the readings are those `days` counts steps between.
- A row takes its tokens times the rate the same call's `week_meters` gives its model under that
  provider and plan; its tokens are `unrated` where it names no model, its login has no reading or
  that reading no plan, or the plan has no rate for its model.
- Each role's and seat's `points` sum exactly and print to six significant digits as the rates
  print, a plan with none not named; `unrated` is whole tokens.  All three roles are always there;
  a history that cannot answer gives all three none and `seats` empty, and one with no `seat_usage`
  table gives `orchestrator` none and `seats` empty.

Black-box: tests/test_key_models_json_week_meters.py's Home, `turn_usage` holding `run_id` and
`role` and `seat_usage` holding `orchestrator` and `effort`; judged by the output and exit code.
Fails against /bin/false.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_models_json_week_meters import ENV, HOUR, TABLES as BASE, THEN, WeekMeters

TABLES = {**BASE,
          "seat_usage": BASE["seat_usage"] + ", orchestrator, effort",
          "turn_usage": "run_id, role, " + BASE["turn_usage"]}
EMPTY = {"executor": {"points": {}, "unrated": 0},
         "reviewer": {"points": {}, "unrated": 0},
         "orchestrator": {"points": {}, "unrated": 0}}


class ModelsJsonRunUsage(WeekMeters):
    def seat(self, ago, tokens, model="anvil-1", account="default", harness="echo",
             orchestrator=None, effort=None):
        """A seat's row of the login `ago` hours before THEN, on `harness`, naming the
        `orchestrator` and `effort` the seat ran as."""
        self.rows["seat_usage"].append((f"{harness}:event-{len(self.rows['seat_usage'])}",
                                        THEN - ago * HOUR, tokens, account, model,
                                        orchestrator, effort))

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

    def runs(self, tables=TABLES):
        return self.answer(tables)["runs"]

    def usage(self, tables=TABLES):
        return self.runs(tables)["usage"]

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
            "reviewer": {"points": {"brine": {"Plus": 10.0033}}, "unrated": 0},
            "orchestrator": {"points": {}, "unrated": 0}})

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
                "reviewer": {"points": {}, "unrated": 6_000},
                "orchestrator": {"points": {"acme": {"Max": 15}}, "unrated": 100_000}}
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
            "reviewer": {"points": {}, "unrated": 0},
            "orchestrator": {"points": {"acme": {"Pro": 10, "Max": 2}}, "unrated": 0}})

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
            "reviewer": {"points": {}, "unrated": 0},
            "orchestrator": {"points": {"acme": {"Max": 10}}, "unrated": 0}})

    def test_a_history_that_cannot_answer_gives_both_roles_none(self):
        self.read(50, 0)
        self.read(40, 10)
        self.turn(45, (100_000, 0, 0, 0))
        # meter_readings without plan, as before plans were kept
        self.rows["meter_readings"] = [row[:-2] for row in self.rows["meter_readings"]]
        runs = self.answer({**TABLES, "meter_readings": (
            "provider, account, meter, used, resets_at, window_secs, at, source, "
            "PRIMARY KEY (provider, account, meter, at)")})["runs"]
        self.assertEqual(runs["usage"], EMPTY)
        self.assertEqual(runs["seats"], [])

    def test_a_login_no_longer_configured_values_its_builds_under_its_plan(self):
        # removed acme login: 10 points for 100,000 tokens -> 100 pts/M; both builds rated
        self.read(50, 10, account="removed")
        self.turn(45, (100_000, 0, 0, 0), account="removed", run_id="fix-api", role="executor")
        self.read(40, 20, account="removed")
        self.turn(35, (50_000, 0, 0, 0), account="removed", run_id="fix-docs", role="executor")
        self.assertEqual(self.usage(), {
            "executor": {"points": {"acme": {"Max": 15}}, "unrated": 0},
            "reviewer": {"points": {}, "unrated": 0},
            "orchestrator": {"points": {}, "unrated": 0}})

    def test_seats_by_orchestrator_and_effort_in_order_and_summed_in_usage(self):
        # acme/Max: 100 pts/M for anvil-1; brine/Plus: 100/3 pts/M for bolt-1 (three seats of
        # 100,000 tokens each print 3.33333 and sum exactly to 10 in usage.orchestrator)
        self.read(50, 0)
        self.seat(45, 100_000, orchestrator="nova", effort="high")
        self.read(40, 10)
        self.read(50, 0, plan="Plus", provider="brine")
        self.seat(45, 100_000, model="bolt-1", harness="chime", orchestrator="nova", effort="high")
        self.seat(44, 100_000, model="bolt-1", harness="chime", orchestrator="bolt", effort="low")
        self.seat(43, 100_000, model="bolt-1", harness="chime")
        self.read(40, 10, plan="Plus", provider="brine")
        # rows days does not count never enter seats or orchestrator usage
        self.seat(35, 0, orchestrator="idle", effort="low")
        self.seat(35, "500", orchestrator="text", effort="low")
        self.seat(35, 100_000, harness="other", orchestrator="other", effort="low")
        self.seat(40 * 24, 100_000, orchestrator="old", effort="low")
        runs = self.runs()
        self.assertEqual(runs["seats"], [
            {"name": "nova", "effort": "high",
             "points": {"acme": {"Max": 10}, "brine": {"Plus": 3.33333}}, "unrated": 0},
            {"name": "bolt", "effort": "low",
             "points": {"brine": {"Plus": 3.33333}}, "unrated": 0},
            {"name": None, "effort": None,
             "points": {"brine": {"Plus": 3.33333}}, "unrated": 0}])
        self.assertEqual(runs["usage"]["orchestrator"], {
            "points": {"acme": {"Max": 10}, "brine": {"Plus": 10}}, "unrated": 0})

    def test_seat_rows_without_model_or_rate_are_unrated(self):
        self.read(50, 0)
        self.turn(45, (100_000, 0, 0, 0))
        self.read(40, 10)
        # after the fitting step so unmodelled rows never discard it
        self.seat(35, 3_000, model=None, orchestrator="nova", effort="high")
        self.seat(35, 4_000, model="", orchestrator="nova", effort="high")
        self.seat(35, 5_000, model="anvil-9", orchestrator="nova", effort="low")
        self.seat(35, 1_000, account="second")              # login with no reading
        runs = self.runs()
        self.assertEqual(runs["seats"], [
            {"name": "nova", "effort": "high", "points": {}, "unrated": 7_000},
            {"name": "nova", "effort": "low", "points": {}, "unrated": 5_000},
            {"name": None, "effort": None, "points": {}, "unrated": 1_000}])
        self.assertEqual(runs["usage"]["orchestrator"], {"points": {}, "unrated": 13_000})

    def test_a_history_without_seat_usage_gives_zero_orchestrator_and_no_seats(self):
        self.read(50, 0)
        self.turn(45, (100_000, 0, 0, 0))
        self.read(40, 10)
        runs = self.answer({name: columns for name, columns in TABLES.items()
                            if name != "seat_usage"})["runs"]
        self.assertEqual(runs["usage"], {
            "executor": {"points": {"acme": {"Max": 10}}, "unrated": 0},
            "reviewer": {"points": {}, "unrated": 0},
            "orchestrator": {"points": {}, "unrated": 0}})
        self.assertEqual(runs["seats"], [])


if __name__ == "__main__":
    unittest.main()
