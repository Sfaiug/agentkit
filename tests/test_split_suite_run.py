"""A measured slow whole suite earns one split run, with ak's concurrent branch check.

Offline: temporary HOME, fake clock, admission and launches; short local proof commands.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, host, run, task, watch, worker
from agentkit import record
import test_suite_pieces as pieces
from test_red_target import make_loop, make_repos


class SplitSuiteRun(unittest.TestCase):
    def setUp(self):
        pieces.SuitePieces.setUp(self)
        self.repo = self.root / "acme"
        self.repo.mkdir()
        run.git(self.repo, "init", "-q", "-b", "main")
        self.cfg = config.load()
        self.lp = SimpleNamespace(state={**record.read_state(self.run_dir),
                                        "repo": str(self.repo), "target": "main",
                                        "base": "origin/main", "launched_session": "seat",
                                        "workers": ["opus"], "reviewers": ["astra"]},
                                  wt=self.repo, run_dir=self.run_dir, cfg=self.cfg,
                                  log=self.logs.append)
        record.save_state(self.run_dir, self.lp.state)
        self.clock, self.prepared, self.spawned = 0, [], []
        self.stack.enter_context(patch.object(run, "prepare", side_effect=self.prepare))
        self.stack.enter_context(patch.object(run, "spawn_bg", side_effect=self.spawn))
        self.stack.enter_context(patch.object(watch, "seat_closed", return_value=False))
        self.stack.enter_context(patch.object(host, "_slice_cpu_stat", return_value=None))
        config.save_session(self.cfg, "seat", "opus", ["astra"])

    def prepare(self, directory, opts, log, cfg, **_kw):
        self.prepared.append((directory, opts))
        record.save_state(directory, {**record.read_state(directory), "run_id": directory.name,
                                      "state": "queued", "slot_waiting": True})

    def spawn(self, directory, argv, **_kw):
        self.spawned.append(directory)

    def measure(self, command="true", attempts=((121, 0, False),)):
        attempts = iter(attempts)
        def limited(argv, limit, output, **_kw):
            seconds, code, killed = next(attempts)
            self.clock += seconds
            output.write(b"fixture suite\n")
            return code, "", killed
        with patch.object(gate.time, "monotonic", side_effect=lambda: self.clock), \
                patch.object(worker, "limited", side_effect=limited):
            gate.run_done_when([command], self.lp.wt, self.run_dir / "gate.log", set(),
                               limit=1000, run_dir=self.run_dir, heavy=True)
        return gate.suite_cost(command, self.lp.wt, self.run_dir)[0]

    def start(self, command="true"):
        gate.split_suite_run(self.lp, command)

    def test_measured_wall_time_without_a_cgroup_and_the_two_minute_floor(self):
        for seconds, count in ((119, 0), (120, 0), (120.01, 1)):
            path = self.measure(attempts=((seconds, 0, False),))
            self.assertAlmostEqual(gate.read_suite_cost(path)["wall_seconds"], seconds)
            self.start()
            self.assertEqual(len(self.spawned), count)
        child = record.read_state(self.spawned[0])
        self.assertEqual(child["launched_session"], "seat")
        self.assertEqual(child["repo"], str(self.repo))
        self.assertEqual(child["workers"], ["astra"])
        self.assertEqual(child["reviewers"], ["astra"])
        self.assertEqual(child["followup"]["run"], self.run_dir.name)
        self.assertEqual(child["split_suite"], "true")
        self.assertTrue(self.prepared[0][1]["--first"])
        meta, body, _ = task.parse_task(self.spawned[0] / "task.md")
        self.assertEqual((meta["repo"], meta["base"], meta["target"]),
                         (str(self.repo), "origin/main", "main"))
        for phrase in ("AK_SHARD=k/N", "1-based", "everything when unset", "--shard=k/N",
                       "conftest", "by position", "no temp dir, port, database or other file",
                       "every test exactly once"):
            self.assertIn(phrase, body)

    def test_wait_time_is_not_suite_time(self):
        def waiting(*_args, **_kw):
            self.clock += 500
        with patch.object(gate, "_acquire_gate_turn", side_effect=waiting):
            path = self.measure(attempts=((119, 0, False),))
        self.assertEqual(gate.read_suite_cost(path)["wall_seconds"], 119)
        self.start()
        self.assertEqual(self.spawned, [])

    def test_retries_are_measured_separately_and_keep_a_slow_attempt(self):
        path = self.measure(attempts=((60, 1, False), (70, 0, False)))
        self.assertEqual(gate.read_suite_cost(path)["wall_seconds"], 70)
        self.start()
        self.assertEqual(self.spawned, [])
        self.measure(attempts=((121, 1, False), (1, 0, False)))
        self.start()
        self.assertEqual(len(self.spawned), 1)

    def test_busy_and_killed_attempts_do_not_earn_a_split(self):
        with patch.object(gate, "busy_turn", return_value=0):
            path = self.measure(attempts=((200, 75, False), (119, 0, False)))
        self.assertEqual(gate.read_suite_cost(path)["wall_seconds"], 119)
        self.start()
        path.unlink()
        self.measure(attempts=((200, worker.TIMEOUT, True),))
        self.assertFalse(path.exists())
        self.start()
        self.assertEqual(self.spawned, [])

    def test_existing_shards_and_another_runs_measurement_start_nothing(self):
        command = "true # AK_SHARD"
        path = gate.suite_cost(command, self.repo, self.run_dir)[0]
        gate.write_suite_cost(path, {"wall_seconds": 300, "run_id": "fixture"})
        self.start(command)
        path = self.measure()
        gate.write_suite_cost(path, {"run_id": "another-run"})
        self.start()
        self.assertEqual(self.spawned, [])

    def test_each_line_gets_one_run_whatever_its_ending_even_after_retention(self):
        path = self.measure()
        self.start()
        directory = self.spawned[0]
        receipt = record.read_state(directory)
        for ending in ("running", "queued", "pass", "fail", "blocked", "not_needed", "stopped"):
            record.save_state(directory, {**receipt, "state": ending})
            self.measure()
            self.start()
            self.assertEqual(self.spawned, [directory], ending)
            self.assertEqual(gate.read_suite_cost(path)["split_run"], directory.name)
        shutil.rmtree(directory)
        self.start()
        self.assertEqual(self.spawned, [directory])
        self.measure("echo changed")
        self.start("echo changed")
        self.assertEqual(len(self.spawned), 2)

    def test_a_changed_line_waits_for_the_repositories_open_split(self):
        self.measure()
        self.start()
        path = self.measure("echo changed")
        self.start("echo changed")
        self.assertEqual(len(self.spawned), 1)
        self.assertNotIn("split_run", gate.read_suite_cost(path))
        directory = self.spawned[0]
        record.save_state(directory, {**record.read_state(directory), "state": "fail"})
        self.start("echo changed")
        self.assertEqual(len(self.spawned), 2)

    def test_repository_and_session_are_taken_from_the_discovering_run(self):
        self.measure()
        self.start()
        other = self.root / "another-project"
        other.mkdir()
        run.git(other, "init", "-q", "-b", "main")
        self.lp.state.update(repo=str(other), launched_session="other-seat")
        self.lp.wt = other
        record.save_state(self.run_dir, self.lp.state)
        self.measure()
        self.start()
        self.assertEqual(len(self.spawned), 2)
        child = record.read_state(self.spawned[-1])
        self.assertEqual(child["repo"], str(other))
        self.assertEqual(child["launched_session"], "other-seat")

    def test_competing_launches_and_a_queued_launch_failure_keep_one_receipt(self):
        self.measure()
        with patch.object(run, "spawn_bg", side_effect=OSError("fixture launch failure")), \
                ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: self.start(), range(3)))
        self.assertEqual(len(self.prepared), 1)
        self.assertTrue(record.read_state(self.prepared[0][0])["slot_waiting"])
        self.start()
        self.assertEqual(len(self.prepared), 1)
        self.assertTrue(any("fixture launch failure" in line for line in self.logs))

    def test_closed_solo_and_seatless_runs_do_not_consume_the_line(self):
        path = self.measure()
        with patch.object(watch, "seat_closed", return_value=True):
            self.start()
        config.update_session("seat", solo=True)
        self.start()
        config.update_session("seat", solo=False)
        self.lp.state["launched_session"] = None
        self.start()
        self.assertEqual(self.spawned, [])
        self.assertNotIn("split_run", gate.read_suite_cost(path))

    def test_final_check_starts_the_split_for_its_declared_suite(self):
        folder = self.root / "landing"
        folder.mkdir()
        _, _, wt = make_repos(folder)
        (wt / "AGENTS.md").write_text("---\ntests: true\n---\n")
        run.git(wt, "add", "AGENTS.md")
        run.git(wt, "commit", "-m", "Declare fixture suite")
        self.lp, self.run_dir, _ = make_loop(folder, wt, ["true # once"], cfg=self.cfg)
        self.lp.state["launched_session"] = "seat"
        record.save_state(self.run_dir, self.lp.state)
        limited = worker.limited
        def suite(argv, limit, **kwargs):
            if argv != ["bash", "-c", "true"]:
                return limited(argv, limit, **kwargs)
            self.clock += 121
            return 0, "", False
        with patch.object(gate.time, "monotonic", side_effect=lambda: self.clock), \
                patch.object(worker, "limited", side_effect=suite):
            self.assertTrue(run.final_check(self.lp, "origin/main"))
        self.assertEqual(len(self.spawned), 1)

    def test_aks_check_reads_the_branch_and_runs_all_three_pieces_concurrently(self):
        self.measure()
        self.start()
        _, body, _ = task.parse_task(self.spawned[0] / "task.md")
        check, = task.done_when(body, self.spawned[0] / "task.md")
        def proof():
            return subprocess.run(["bash", "-c", check], cwd=self.repo,
                                  capture_output=True, text=True, timeout=15,
                                  env={**os.environ, "AK_SHARD": "99/99"})
        for declaration in ("", "---\ntests: true\n---\n"):
            (self.repo / "AGENTS.md").write_text(declaration)
            self.assertNotEqual(proof().returncode, 0)
        (self.repo / "suite.py").write_text('''import os, pathlib, sys, time
k, n = map(int, os.environ["AK_SHARD"].split("/"))
assert n == 3
root = pathlib.Path("proof")
root.mkdir(exist_ok=True)
(root / f"started-{k}").touch()
until = time.monotonic() + 5
while len(list(root.glob("started-*"))) < n:
    assert time.monotonic() < until, "pieces were run serially"
    time.sleep(0.01)
(root / f"tests-{k}").write_text(" ".join(str(i) for i in range(9) if i % n == k - 1))
sys.exit(3 if k == 2 and pathlib.Path("fail").exists() else 0)
''')
        (self.repo / "AGENTS.md").write_text("---\ntests: python3 suite.py # AK_SHARD\n---\n")
        result = proof()
        self.assertEqual(result.returncode, 0, result.stderr)
        tests = [int(test) for path in (self.repo / "proof").glob("tests-*")
                 for test in path.read_text().split()]
        self.assertCountEqual(tests, range(9))
        shutil.rmtree(self.repo / "proof")
        (self.repo / "fail").touch()
        self.assertNotEqual(proof().returncode, 0)
        self.assertEqual(len(list((self.repo / "proof").glob("tests-*"))), 3)


if __name__ == "__main__":
    unittest.main()
