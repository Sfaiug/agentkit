"""`ak run status` lists the last seven days of runs and counts the rest; `--history` lists all.

A run that ended over seven days ago and needs nothing more is history: the listing leaves it
out and says how many it left out, so what the owner and the orchestrator read is what is
current, while a passed run still waiting to be delivered stays however old it is.
`--history` brings every run back, with the scoreboard after them, and `--plain` is the line
format a script reads, each run with its result and record paths.  A record written with the
old per-task time budgets runs under today's fixed limits.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on run records written under HOME.
"""

import json
import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

DAY = 86400
HIDDEN = "{} older run(s) hidden; ak run status --history [--json] shows full history"
SCOREBOARD = "Scoreboard (reported tokens; size now and 7 days ago)"
RUN_ID = re.compile(r"\d{8}-\d{4}-")
LIMITS = "  limits: silence_minutes=20, ceiling_hours=6"


def ended(home, slug, days, **fields):
    """A run that ended `days` ago, as its loop left the record; returns its id."""
    finished = time.time() - days * DAY
    run_id = time.strftime("%Y%m%d-%H%M-", time.gmtime(finished)) + slug
    home.write(f".agentkit/runs/{run_id}/run.json", {
        "run_id": run_id, "title": slug.replace("-", " ").capitalize(), "state": "pass",
        "verdict": "PASS", "executor": "opus", "reviewer": "astra", "rounds": 3,
        "started_at": finished - 1800, "finished_at": finished, **fields})
    return run_id


def row(out, run_id):
    rows = [line for line in out.splitlines() if line.startswith(run_id)]
    if len(rows) != 1:
        raise AssertionError(f"{run_id} has {len(rows)} rows in:\n{out}")
    return rows[0]


class SevenDayWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.recent = ended(cls.home, "fix-api", 6, no_merge=True)
        cls.old = ended(cls.home, "tidy-logs", 8, no_merge=True)
        cls.merged = ended(cls.home, "add-beta", 90, repo=str(cls.home.path / "code/acme"),
                           merged=True, pr="https://github.com/acme/acme/pull/7")
        # passed and never delivered: somebody still has to merge it
        cls.waiting = ended(cls.home, "ship-gamma", 30, repo=str(cls.home.path / "code/acme"))
        cls.current = {cls.recent, cls.waiting}
        cls.every = cls.current | {cls.old, cls.merged}

    def status(self, *args):
        done = self.home.ak("run", "status", *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def ids(self, *args):
        return {entry["run_id"] for entry in json.loads(self.status(*args, "--json"))}

    def test_runs_that_ended_over_seven_days_ago_are_left_out_and_counted(self):
        out = self.status()
        for run_id in self.current:
            self.assertIn("✓ done", row(out, run_id))
        for run_id in (self.old, self.merged):
            self.assertNotIn(run_id, out)
        self.assertEqual(out.splitlines()[-1], HIDDEN.format(2))

    def test_json_leaves_out_the_same_runs_and_nothing_else_is_printed(self):
        self.assertEqual(self.ids(), self.current)

    def test_history_lists_every_run_then_the_scoreboard(self):
        out = self.status("--history")
        for run_id in self.every:
            self.assertIn("✓ done", row(out, run_id))
        lines = out.splitlines()
        at = lines.index(HIDDEN.format(0))
        self.assertEqual(lines[at + 1], SCOREBOARD)
        self.assertEqual(self.ids("--history"), self.every)

    def test_plain_gives_each_run_a_line_with_its_result_and_record_paths(self):
        out = self.status("--plain")
        lines = out.splitlines()
        for run_id in self.current:
            line = row(out, run_id)
            self.assertEqual(line.split()[:3], [run_id, "pass", "PASS"])
            folder = self.home.path / ".agentkit/runs" / run_id
            self.assertEqual(lines[lines.index(line) + 1],
                             f"  result: {folder}/result.md  record/logs: {folder}")
        self.assertEqual(lines[-1], HIDDEN.format(2))
        self.assertEqual({line.split()[0] for line in lines if RUN_ID.match(line)},
                         self.current)


class OldTimeBudgets(unittest.TestCase):
    def test_a_record_with_the_old_budgets_runs_under_todays_limits(self):
        with Home() as home:
            run_id = ended(home, "fix-api", 0, no_merge=True, done_when_minutes=30,
                           turn_hours=2, stall_minutes=15)
            done = home.ak("run", "status", run_id)
            self.assertEqual(done.code, 0, done.err)
            self.assertIn(LIMITS, done.out.splitlines())
            # the look rewrote the record, and the old budgets went with the rewrite
            record = json.loads((home.path / f".agentkit/runs/{run_id}/run.json").read_text())
            shown = json.loads(home.ak("run", "status", "--json").out)
            for found in (record, *shown):
                self.assertEqual((found["silence_minutes"], found["ceiling_hours"]), (20, 6))
                for key in ("done_when_minutes", "turn_hours", "stall_minutes"):
                    self.assertNotIn(key, found)
            self.assertEqual([entry["run_id"] for entry in shown], [run_id])


if __name__ == "__main__":
    unittest.main()
