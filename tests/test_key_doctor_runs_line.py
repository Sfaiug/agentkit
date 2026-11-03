"""Doctor counts runs and owed endings, and fails when a dead run outlasts two ticks.

Black-box through AK_BIN, with a temporary HOME, the fixture clock and a fake process table.
No tick resumes anything here: doctor only reads the records and reports what is stuck.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, REPO, Home

NOW = 1_800_000_000
CLOCK = """
import io, json, os, sys, time
from types import SimpleNamespace
if sys.argv[:1] == [{ak!r}]:
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.clock import Clock
    from agentkit import host, watch
    watch.time = Clock(time.sleep)
    watch.time.time = lambda: {now}
    table = {{os.getpid() if pid == "self" else int(pid): row
              for pid, row in json.load(open({table!r})).items()}}
    watch._proc_table = lambda: {{pid: row[:3] for pid, row in table.items()}}
    watch.worker.os = SimpleNamespace(**vars(os))
    watch.worker.os.listdir = lambda path: [str(pid) for pid in table]
    def proc_open(path, *_args, **_kw):
        row = table[int(path.split("/")[2])]
        return io.BytesIO((f"AGENTKIT_RUN={{row[3]}}\\0" if len(row) > 3 else "").encode())
    watch.worker.open = proc_open
    host.alive = lambda pid: pid in table
    host.process_identity = lambda pid: None
    host.proc_stat = lambda pid: (host.ProcStat(table[pid][1], table[pid][0], 0, 0)
                                  if pid in table else None)
"""


class DoctorRunsLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        table = self.home.write("fakes/processes.json", {})
        self.home.write("fakes/sitecustomize.py", CLOCK.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), tests=str(REPO / "tests"),
            now=NOW, table=str(table)))
        self.env = {"PYTHONPATH": str(table.parent)}
        self.tick()

    def tick(self, took=100):
        self.home.write(".agentkit/state/watch.json", {"tick": {
            "started_at": NOW - 10 - took, "ended_at": NOW - 10,
            "slowest": {"pass": "dead loops", "seconds": took}}})

    def run_record(self, name, state="running", ago=250, **fields):
        record = {"run_id": name, "title": "Fix api", "state": state,
                  "started_at": NOW - 10000, "launched_session": "acme", **fields}
        if state in ("pass", "fail", "blocked", "stopped"):
            record.setdefault("finished_at", NOW - ago)
        path = self.home.write(f".agentkit/runs/{name}/run.json", record)
        os.utime(path, (NOW - ago, NOW - ago))
        return path.parent

    def doctor(self, code, line):
        runs = self.home.path / ".agentkit/runs"
        tick = self.home.path / ".agentkit/state/watch.json"

        def kept():
            return {path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in [*runs.rglob("*"), tick] if path.is_file()}

        before = kept()
        done = self.home.ak("doctor", env=self.env)
        self.assertEqual(done.code, code, done.out + done.err)
        self.assertIn(f"runs  {line}", done.out.splitlines())
        self.assertTrue(done.out.splitlines()[-1].startswith("rented machines: "), done.out)
        self.assertEqual(kept(), before, "doctor must leave the run and tick records alone")

    def test_going_ended_and_owed_with_the_oldest_age(self):
        self.run_record("moving", pid=41, ago=1000)
        self.home.write("fakes/processes.json", {41: [1, "S", ["python"]]})
        self.run_record("said", "pass", ago=60, handed_back=NOW - 50)
        self.run_record("owed", "blocked", ago=600, handback_pending=True)
        self.doctor(0, "1 going · 2 ended today · 1 ending owed, oldest 10m")

    def test_a_dead_run_after_two_ticks_fails_after_the_rest_of_the_report(self):
        self.run_record("lost")
        self.doctor(1, "1 going · 0 ended today · 0 endings owed · "
                       "dead: lost (4m since last write)")

    def test_a_dead_run_short_of_two_ticks_is_named_without_failing(self):
        self.run_record("lost", ago=150)
        self.doctor(0, "1 going · 0 ended today · 0 endings owed · "
                       "dead: lost (2m since last write)")

    def test_the_last_ticks_length_and_the_cron_floor_set_the_boundary(self):
        for took, grace in ((10, 180), (100, 200), (400, 800)):
            for age, code in ((grace - 1, 0), (grace, 1)):
                with self.subTest(took=took, age=age):
                    self.tick(took)
                    self.run_record("lost", ago=age)
                    self.doctor(code, "1 going · 0 ended today · 0 endings owed · "
                                      f"dead: lost ({age // 60}m since last write)")

    def test_old_endings_still_owed_are_shown_without_failing(self):
        self.run_record("old", "fail", ago=10, finished_at=NOW - 2 * 86400)
        self.run_record("new", "pass", ago=600)
        self.run_record("reported", "pass", reported=True)
        self.run_record("said", "blocked", handed_back=True)
        self.run_record("stopped", "stopped")
        self.doctor(0, "0 going · 4 ended today · 2 endings owed, oldest 2d")

    def test_a_marked_worker_keeps_its_run_alive_without_the_loop(self):
        directory = self.run_record("moving")
        self.home.write("fakes/processes.json", {
            42: [1, "S", ["sleep", "600"], str(directory)]})
        self.doctor(0, "1 going · 0 ended today · 0 endings owed")

    def test_a_marked_parent_worker_keeps_its_run_alive_when_it_calls_doctor(self):
        directory = self.run_record("moving", pid=41)
        marker = str(directory / "turn-acme")
        self.home.write("fakes/processes.json", {
            42: [1, "S", ["bash", "adapter.sh"], marker],
            "self": [42, "S", [sys.executable, AK, "doctor"], marker]})
        self.doctor(0, "1 going · 0 ended today · 0 endings owed")

    def test_a_resume_starting_before_its_pid_is_recorded_is_live(self):
        self.run_record("moving")
        self.home.write("fakes/processes.json", {
            42: [1, "S", [sys.executable, AK, "run", "resume", "moving"]]})
        self.doctor(0, "1 going · 0 ended today · 0 endings owed")

    def test_log_readers_and_editors_do_not_hide_a_dead_run(self):
        directory = self.run_record("lost", pid=41)
        for args in (["tail", "-F", str(directory / "log.txt")],
                     ["vim", str(directory / "result.md")],
                     ["tail", "-F", AK, "run", "resume", "lost"]):
            with self.subTest(args=args):
                self.home.write("fakes/processes.json", {42: [1, "S", args]})
                self.doctor(1, "1 going · 0 ended today · 0 endings owed · "
                               "dead: lost (4m since last write)")

    def test_zombies_and_another_runs_paths_do_not_keep_a_dead_run_alive(self):
        directory = self.run_record("lost", pid=41)
        self.home.write("fakes/processes.json", {
            41: [1, "Z", ["ak", "run", "resume", "lost"], str(directory)],
            42: [1, "S", ["sleep", "600"], str(directory) + "-other"],
            43: [1, "S", ["printf", "lost"]]})
        self.doctor(1, "1 going · 0 ended today · 0 endings owed · "
                       "dead: lost (4m since last write)")


if __name__ == "__main__":
    unittest.main()
