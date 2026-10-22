"""`ak run status --json` prints the runs as one JSON list: each run's record and its paths.

Models, scripts and dashboards read a run's state and where its files are from this list, not
from the table a person reads, so its shape is a contract: one row per run directory, each the
fields of its run.json as written plus a `paths` object naming the result, the record, the logs
and the checkout, and whether that checkout is still there.  A record nobody can read is a row
that says so, never a failed command that hides every other run, and stdout is the JSON alone,
without the host line the table starts with.  Naming a run lists that run alone, still as a list.

Black-box: the records are written by hand where ak keeps them, and the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

PASSED, MISSING = "20261019-1200-a", "20261019-1400-d"
# A record that is not JSON, one that is JSON but no record, and a run directory with none yet.
UNREADABLE = {"20261019-1200-b": "{not json", "20261019-1200-f": "[1, 2]",
              "20261019-1200-g": None}
PATH_KEYS = {"result", "record", "logs", "workspace", "workspace_present"}


class RunStatusJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.runs = cls.home.path / ".agentkit" / "runs"
        cls.checkout = cls.home.path / ".agentkit" / "wt" / PASSED
        cls.checkout.mkdir(parents=True)
        now = time.time()
        cls.records = {
            PASSED: {"state": "pass", "verdict": "PASS", "title": "fix api", "rounds": 3,
                     "started_at": now - 600, "finished_at": now - 30, "repo": None,
                     "scratch": True, "no_merge": True, "branch": "ak/fix-api",
                     "worktree": str(cls.checkout)},
            "20261019-1300-c": {"state": "fail", "verdict": "FAIL", "title": "beta",
                                "started_at": now - 900, "finished_at": now - 120,
                                "repo": None, "scratch": True},
            # its checkout already removed
            MISSING: {"state": "stopped", "title": "gamma", "started_at": now - 900,
                      "finished_at": now - 200, "repo": None, "scratch": True,
                      "worktree": str(cls.home.path / ".agentkit" / "wt" / MISSING)},
            "20261019-1500-e": {"state": "blocked", "title": "delta", "error": "cannot be done",
                                "started_at": now - 900, "finished_at": now - 300,
                                "repo": None, "scratch": True},
        }
        for run_id, record in cls.records.items():
            record["run_id"] = run_id
            cls.home.write(f".agentkit/runs/{run_id}/run.json", record)
        for run_id, text in UNREADABLE.items():
            if text is None:
                (cls.runs / run_id).mkdir(parents=True)
            else:
                cls.home.write(f".agentkit/runs/{run_id}/run.json", text)

    def listed(self, *args):
        done = self.home.ak("run", "status", "--json", *args)
        self.assertEqual(done.code, 0, done.err)
        rows = json.loads(done.out)    # the whole of stdout, so no line but the JSON
        self.assertIsInstance(rows, list)
        return rows

    def by_id(self, *args):
        return {row["run_id"]: row for row in self.listed(*args)}

    def test_the_list_has_one_row_per_run_and_no_host_line(self):
        done = self.home.ak("run", "status", "--json")
        self.assertEqual(done.code, 0, done.err)
        self.assertFalse([line for line in done.out.splitlines() if line.startswith("host:")])
        self.assertEqual(sorted(row["run_id"] for row in json.loads(done.out)),
                         sorted([*self.records, *UNREADABLE]))

    def test_each_row_carries_every_field_of_its_record_as_written(self):
        rows = self.by_id()
        for run_id, record in self.records.items():
            with self.subTest(run_id):
                for key, value in record.items():
                    self.assertEqual(rows[run_id].get(key), value, key)

    def test_paths_name_the_result_the_record_and_the_logs_in_the_runs_directory(self):
        for run_id, row in self.by_id().items():
            with self.subTest(run_id):
                paths = row["paths"]
                self.assertEqual(set(paths), PATH_KEYS)
                self.assertEqual(paths["result"], str(self.runs / run_id / "result.md"))
                self.assertEqual(paths["record"], str(self.runs / run_id / "run.json"))
                self.assertEqual(paths["logs"], str(self.runs / run_id))
                self.assertIs(type(paths["workspace_present"]), bool)

    def test_a_checkout_is_named_and_present_only_while_its_directory_exists(self):
        rows = self.by_id()
        self.assertEqual(rows[PASSED]["paths"]["workspace"], str(self.checkout))
        self.assertIs(rows[PASSED]["paths"]["workspace_present"], True)
        self.assertEqual(rows[MISSING]["paths"]["workspace"], self.records[MISSING]["worktree"])
        self.assertIs(rows[MISSING]["paths"]["workspace_present"], False)
        without = rows["20261019-1300-c"]["paths"]
        self.assertIsNone(without["workspace"])
        self.assertIs(without["workspace_present"], False)

    def test_a_record_that_cannot_be_read_is_an_unreadable_row_beside_the_others(self):
        rows = self.by_id()
        for run_id in UNREADABLE:
            with self.subTest(run_id):
                self.assertEqual(rows[run_id]["state"], "unreadable")
                self.assertEqual(rows[run_id]["paths"]["record"],
                                 str(self.runs / run_id / "run.json"))
        self.assertEqual(rows[PASSED]["state"], "pass")

    def test_naming_a_run_lists_that_run_alone(self):
        rows = self.listed(PASSED)
        self.assertEqual(len(rows), 1)
        for key, value in self.records[PASSED].items():
            self.assertEqual(rows[0].get(key), value, key)
        self.assertEqual(rows[0]["paths"]["record"], str(self.runs / PASSED / "run.json"))
        self.assertIs(rows[0]["paths"]["workspace_present"], True)
        rows = self.listed("20261019-1200-b")
        self.assertEqual([(row["run_id"], row["state"]) for row in rows],
                         [("20261019-1200-b", "unreadable")])


if __name__ == "__main__":
    unittest.main()
