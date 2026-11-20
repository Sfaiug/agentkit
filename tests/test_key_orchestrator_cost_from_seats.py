"""`ak models --json` prices the orchestrator's row of a model at an effort (`task_usage`, its
measured `cost`) at what its seats used a task: the points of a week every `seat_usage` row
naming that model and effort took, at listed prices, times 100 over each row's login's
`week_listed_usd` (`ak usage --json`), a subagent's on another model too, over the task runs that
ended naming them and started no earlier than the first such row.  The orchestrator's other rows
are scaled by what those seats paid a board dollar, not by what the worker roles' runs paid.  A
model and effort no such run names, a row with no listed price or a login with no week leaves no
share.

Black-box through tests/fixtures/akbin.py on tests/fixtures/meters.py's harness, with
tests/test_key_role_cost_from_runs.py's boards, plans and readings in its Home and seat rows and
runs naming their orchestrator.  Fails against /bin/false.
"""

from contextlib import closing
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_key_role_cost_from_runs as from_runs
from test_key_role_cost_from_runs import DAY, NOW, History

# what History's tables lack for an orchestrator, as history.db names it
ORCHESTRATING = {"seat_usage": ("orchestrator", "effort"),
                 "runs": ("orchestrator", "orchestrator_effort", "started_at")}
# the hour the seats first used anything, after the logins' weeks were read
FIRST = NOW - 1.5 * DAY


class Seats(History):
    """A History holding seat rows and task runs as a seat orchestrating with a model and effort
    keeps them."""

    def __init__(self, history):
        vars(self).update(vars(history))
        self.orchestrated = {table: [] for table in ORCHESTRATING}

    def seat(self, orchestrating, rows, at=FIRST):
        """A seat orchestrating with (model, effort) using `rows`, (account, model, counts) each,
        at `at`."""
        self.orchestrated["seat_usage"] += [
            (f"echo:usage-{len(self.orchestrated['seat_usage'])}-{n}", at, sum(counts), account,
             model, *counts, *orchestrating) for n, (account, model, counts) in enumerate(rows)]

    def launch(self, orchestrating, started, ended=True):
        """A task run the seat orchestrating with (model, effort) launched at `started`, ended
        unless not `ended`."""
        self.orchestrated["runs"].append((f"launched-{len(self.orchestrated['runs'])}", "task",
                                          NOW - DAY / 2 if ended else None, *orchestrating,
                                          started))

    def save(self):
        super().save()
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            for table, columns in ORCHESTRATING.items():
                for column in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            for row in self.orchestrated["seat_usage"]:
                db.execute("INSERT INTO seat_usage (event, at, tokens, account, model, input, "
                           "cache_write, cache_read, output, orchestrator, effort) "
                           f"VALUES ({', '.join('?' * len(row))})", row)
            for row in self.orchestrated["runs"]:
                db.execute("INSERT INTO runs (run_id, kind, finished_at, orchestrator, "
                           "orchestrator_effort, started_at) VALUES (?, ?, ?, ?, ?, ?)", row)


class OrchestratorCostFromSeats(unittest.TestCase):
    # its Home and readings, read off its module so that its own cases are not run here too
    Runs = from_runs.RoleCostFromRuns
    answer, points, assertCost = Runs.answer, Runs.points, Runs.assertCost

    def setUp(self):
        self.Runs.setUp(self)   # its logins' weeks: $20 the usual one's, $10 the second's
        self.history = Seats(self.history)

    def test_its_seats_use_a_task_measures_its_row_and_scales_its_others(self):
        own = [("default", "anvil-1", (1_000_000, 0, 2_000_000, 100_000))]
        subagent = [("second", "bloom-1", (100_000, 0, 0, 20_000))]
        self.history.seat(("anvil", "high"), own)
        self.history.seat(("anvil", "high"), subagent, at=NOW - DAY)
        # counted: a run launched as the first row was kept, and one after
        for started in (FIRST, NOW - 1.2 * DAY):
            self.history.launch(("anvil", "high"), started)
        # not: one before any row, one running, one at another effort or of another model
        self.history.launch(("anvil", "high"), NOW - 2 * DAY)
        self.history.launch(("anvil", "high"), NOW - 1.1 * DAY, ended=False)
        self.history.launch(("anvil", "low"), NOW - DAY)
        self.history.launch(("bloom", "high"), NOW - DAY)
        # a build that pays a board dollar more than the seats do
        built = [("default", "anvil-1", (2_000_000, 0, 0, 0))]
        self.history.run(("anvil", "high"), built=[built])
        weeks, answer = self.answer()
        orchestrator = self.points(weeks, own, subagent) / 2
        self.assertAlmostEqual(answer["task_usage"]["anvil"]["high"]["orchestrator"],
                               orchestrator)
        self.assertCost(answer, "orchestrate", "anvil-1", "measured", orchestrator)
        # Crown orchestrated nothing: its board dollars, 40, scaled as Anvil's seats scale its 10
        self.assertCost(answer, "orchestrate", "crown-1", "provider", 40 * orchestrator / 10)
        self.assertCost(answer, "execute", "crown-1", "provider",
                        40 * self.points(weeks, built) / 10)

    def test_a_pair_with_no_run_since_its_first_row_an_unpriced_row_or_no_week_has_no_share(self):
        priced = [("default", "anvil-1", (1_000_000, 0, 0, 0))]
        self.history.seat(("bloom", "high"), priced)
        self.history.launch(("bloom", "high"), NOW - 2 * DAY)
        self.history.seat(("crown", "high"), priced + [("default", "easel-2", (1, 0, 0, 0))])
        self.history.seat(("anvil", "high"), priced + [("third", "anvil-1", (1, 0, 0, 0))])
        self.history.seat(("anvil", "low"), priced)
        for orchestrating in (("crown", "high"), ("anvil", "high"), ("anvil", "low")):
            self.history.launch(orchestrating, NOW - 1.2 * DAY)
        weeks, answer = self.answer()
        found = answer["task_usage"]
        self.assertEqual({model: {effort: list(roles) for effort, roles in efforts.items()}
                          for model, efforts in found.items()},
                         {"anvil": {"low": ["orchestrator"]}})
        self.assertAlmostEqual(found["anvil"]["low"]["orchestrator"], self.points(weeks, priced))


if __name__ == "__main__":
    unittest.main()
