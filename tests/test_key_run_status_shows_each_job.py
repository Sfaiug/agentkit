"""`ak run status` shows each recent job as a block: its count line, a line when its launcher is
gone, and each task's verdict line.

A job is a seat's launch of several tasks at once (`ak run a.md b.md`), its receipt
`jobs/<id>/job.json`.  Its block opens `job <id>: ` with how many of its tasks are in each state,
running and queued first, then merged, passed, skipped, failed, blocked and stopped, then any
other word a task's run gave.  A job whose launcher is no longer alive says so on the next line,
and whose it is to go on.  Then each task that has a verdict says it, indented: a task that
ended reads its run as it stands now, a blocked one with the error its run recorded.  Blocks go
newest started first; one that finished more than seven days ago is history, shown only with
`--history`; and run from a seat, only that seat's jobs show.

Black-box: runs and receipts are records written by hand where ak keeps them, and the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py; this test fails against
`/bin/false`.
"""

from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, owner

DAY = 86400
GONE = "  launcher gone; ak run resume {0} to continue, ak run stop {0} to end it"
REVIEW = {"executor": "opus", "reviewer": "astra", "executor_provider": "anthropic",
          "reviewer_provider": "openai", "verdict": "PASS", "returncode": 0, "done_when": True}


def record(home, run_id, **fields):
    home.write(f".agentkit/runs/{run_id}/run.json",
               {"run_id": run_id, "executor": "opus", "reviewer": "astra", **fields})


def receipt(home, job_id, *tasks, **fields):
    home.write(f".agentkit/jobs/{job_id}/job.json",
               {"job_id": job_id, "tasks": list(tasks), **fields})


def task(name, state, run_id=None, **fields):
    return {"name": name, "state": state, "run_id": run_id, **fields}


def launcher(test, exited=False):
    """The identity the `ak run` that launched a job records, of a process still running, as
    that launcher is, or of one since `exited`."""
    keeper = subprocess.Popen(["sleep", "3600"], start_new_session=True)
    test.addCleanup(lambda: (keeper.kill(), keeper.wait()))
    identity = owner(keeper.pid)
    if exited:
        keeper.kill()
        keeper.wait()
    return identity


def ended(home, job_id, started, finished, **fields):
    """A job of one merged task, launched at `started` and finished at `finished`."""
    receipt(home, job_id, task("ship.md", "merged",
                               verdict_line="ship.md: PASS, merged after 2 rounds"),
            started_at=started, finished_at=finished, **fields)


def blocks(out):
    """Each job's block as printed: its `job` line and the indented lines under it."""
    found, inside = [], False
    for line in out.splitlines():
        if line.startswith("job "):
            found.append([line])
            inside = True
        elif inside and line.startswith("  "):
            found[-1].append(line)
        else:
            inside = False
    return found


class RunStatusShowsEachJob(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def status(self, *args, env=None):
        done = self.home.ak("run", "status", *args, env=env)
        self.assertEqual(done.code, 0, done.out + done.err)
        return blocks(done.out)

    def heads(self, *args, env=None):
        return [block[0] for block in self.status(*args, env=env)]

    def test_a_job_counts_its_tasks_by_state_and_says_each_verdict(self):
        home, now = self.home, time.time()
        alive = launcher(self)
        record(home, "20261107-0900-merge-the-api", title="Merge the API", state="pass",
               verdict="PASS", merged=True, pr="https://github.com/acme/widget/pull/7",
               round_summaries=[{}, {}], finished_at=now - 3000)
        record(home, "20261107-0901-pass-the-docs", title="Pass the docs", state="pass",
               verdict="PASS", no_merge=True, review=REVIEW, round_summaries=[{}, {}],
               finished_at=now - 2400)
        record(home, "20261107-0902-fail-the-parser", title="Fail the parser", state="fail",
               verdict="FAIL", round_summaries=[{}, {}, {}], finished_at=now - 1800)
        record(home, "20261107-0903-block-the-token", title="Block the token", state="blocked",
               error="no token\n  for the API", round_summaries=[{}], finished_at=now - 1200)
        record(home, "20261107-0904-run-the-tally", title="Run the tally", state="running",
               round_summaries=[{}], started_at=now - 600, **alive)
        # listed against the count line's order: the count line keeps its own
        receipt(home, "20261107-090000-merge-the-api",
                task("block-the-token.md", "blocked", "20261107-0903-block-the-token"),
                task("fail-the-parser.md", "failed", "20261107-0902-fail-the-parser"),
                task("skip-the-notes.md", "skipped", verdict_line="skip-the-notes.md: not started"),
                task("pass-the-docs.md", "passed", "20261107-0901-pass-the-docs"),
                task("merge-the-api.md", "merged", "20261107-0900-merge-the-api"),
                task("run-the-tally.md", "running", "20261107-0904-run-the-tally"),
                started_at=now - 3600, finished_at=None, **alive)
        self.assertEqual(self.status(), [[
            "job 20261107-090000-merge-the-api: 1 running, 1 merged, 1 passed, 1 skipped, "
            "1 failed, 1 blocked",
            "  block-the-token.md: BLOCKED: no token for the API",
            "  fail-the-parser.md: FAIL after 3 rounds: needs you",
            "  skip-the-notes.md: not started",
            "  pass-the-docs.md: PASS, passed after 2 rounds",
            "  merge-the-api.md: PASS, merged after 2 rounds https://github.com/acme/widget/pull/7"]])

    def test_a_job_whose_launcher_is_gone_says_so_under_its_count_line(self):
        home, now = self.home, time.time()
        exited = launcher(self, exited=True)
        record(home, "20261107-0900-merge-the-api", title="Merge the API", state="pass",
               verdict="PASS", merged=True, round_summaries=[{}, {}], finished_at=now - 1200)
        record(home, "20261107-0901-fail-the-parser", title="Fail the parser", state="fail",
               verdict="FAIL", round_summaries=[{}, {}], finished_at=now - 600)
        # the launcher died before it wrote the second task's ending: its run's ending counts
        receipt(home, "20261107-090000-merge-the-api",
                task("merge-the-api.md", "merged", "20261107-0900-merge-the-api"),
                task("fail-the-parser.md", "running", "20261107-0901-fail-the-parser"),
                started_at=now - 3600, finished_at=None, **exited)
        self.assertEqual(self.status(), [[
            "job 20261107-090000-merge-the-api: 1 merged, 1 failed",
            GONE.format("20261107-090000-merge-the-api"),
            "  merge-the-api.md: PASS, merged after 2 rounds",
            "  fail-the-parser.md: FAIL after 2 rounds: needs you"]])

    def test_the_newest_started_job_shows_first(self):
        now = time.time()
        ended(self.home, "20261107-090000-ship-early", now - 7200, now - 6000)
        ended(self.home, "20261107-093000-ship-later", now - 5400, now - 4800)
        self.assertEqual(self.heads(), ["job 20261107-093000-ship-later: 1 merged",
                                        "job 20261107-090000-ship-early: 1 merged"])

    def test_a_job_finished_over_seven_days_ago_is_history(self):
        now = time.time()
        ended(self.home, "20261030-090000-ship-old", now - 8 * DAY - 600, now - 8 * DAY)
        ended(self.home, "20261101-090000-ship-recent", now - 6 * DAY - 600, now - 6 * DAY)
        self.assertEqual(self.heads(), ["job 20261101-090000-ship-recent: 1 merged"])
        self.assertEqual(self.heads("--history"), ["job 20261101-090000-ship-recent: 1 merged",
                                                   "job 20261030-090000-ship-old: 1 merged"])

    def test_run_from_a_seat_only_that_seats_jobs_show(self):
        now = time.time()
        ended(self.home, "20261107-090000-ship-acme", now - 7200, now - 6000, seat="acme")
        ended(self.home, "20261107-093000-ship-atoll", now - 5400, now - 4800, seat="atoll")
        self.assertEqual(self.heads(env={"AGENTKIT_SESSION": "acme"}),
                         ["job 20261107-090000-ship-acme: 1 merged"])


if __name__ == "__main__":
    unittest.main()
