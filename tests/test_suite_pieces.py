"""Opted-in suites share a checkout, host capacity and ceiling; retries run alone.

Offline: temporary HOME, injected host/cgroup readings and short fixture commands.
"""

from collections import Counter
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, host, run, worker
from agentkit import record
from test_red_target import make_loop, make_repos

ROOM = {"cpus": 4, "load": 0, "free_mb": 820,
        "slice_cpu_quota": 4, "slice_cpu_used": 0,
        "slice_memory_high_mb": 820, "slice_memory_used_mb": 0}
SUITE = 'printf "piece %s\\n" "${AK_SHARD:-all}"'


class SuitePieces(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-suite-pieces-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_HOST_READINGS": json.dumps(ROOM),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(gate, "_running_commands", return_value=["fixture"]))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.01))
        self.run_dir = config.RUNS / "fixture"
        self.run_dir.mkdir()
        record.save_state(self.run_dir, {"run_id": "fixture", "state": "running",
                                        "repo": str(self.root), "round_summaries": []})
        self.logs = []

    def check(self, commands=None, **kwargs):
        return gate.run_done_when(commands or [SUITE], self.root,
                                  self.run_dir / "gate.log", set(), limit=10,
                                  log=self.logs.append, run_dir=self.run_dir, **kwargs)

    def test_pieces_get_separate_headers_and_one_command_outcome(self):
        with patch.dict(os.environ, {"AK_SHARD": "99/99"}):
            ok, text = self.check()
        self.assertTrue(ok, text)
        for shard in ("1/2", "2/2"):
            self.assertIn(f"--- AK_SHARD={shard} ---\n[exit 0]\npiece {shard}", text)
        self.assertEqual(run.done_when_counts(text, [SUITE]), (1, 1))
        self.assertEqual((self.run_dir / "gate.log").read_text(), text)
        self.assertEqual(list(self.run_dir.glob("*-piece-*.log")), [])

    def test_a_line_without_the_name_runs_once_without_an_inherited_shard(self):
        calls = []
        def limited(cmd, limit, env, **_kw):
            calls.append(env.get("AK_SHARD"))
            return 0, "", False
        with patch.object(worker, "limited", side_effect=limited), \
                patch.dict(os.environ, {"AK_SHARD": "2/8"}):
            self.assertTrue(self.check(["true"])[0])
        self.assertEqual(calls, [None])

    def test_count_follows_memory_and_cpu_contention_and_never_drops_below_one(self):
        for readings, count in ((ROOM, 2), ({**ROOM, "slice_memory_high_mb": 1640}, 4),
                                ({**ROOM, "slice_cpu_used": 3}, 1),
                                ({**ROOM, "unit_limits": [[100, 500]]}, 1),
                                ({**ROOM, "slice_memory_used_mb": 820}, 1), ({}, 1)):
            with self.subTest(readings=readings), patch.dict(os.environ, {
                    "AK_HOST_READINGS": json.dumps(readings)}):
                ok, text = self.check()
                self.assertTrue(ok, text)
                self.assertEqual(text.count("--- AK_SHARD="), count)
                self.assertIn(f"--- AK_SHARD={count}/{count} ---", text)

    def test_hard_memory_caps_bound_pieces_at_admission_and_without_a_turn(self):
        root = self.root / "cgroups"
        part = root / "agentkit.slice"
        scope = part / "agentkit-run-acme.scope"
        scope.mkdir(parents=True)
        proc = self.root / "proc"
        proc.mkdir()
        (proc / "meminfo").write_text("MemAvailable: 33554432 kB\nMemTotal: 33554432 kB\n")
        (proc / "loadavg").write_text("0 0 0\n")
        membership = proc / "cgroup"
        membership.write_text("0::/agentkit.slice/agentkit-run-acme.scope\n")
        for high, cap, used, parent_high, parent_cap, parent_used, count in (
                ("max", 1024, 0, 16384, "max", 0, 2),
                ("max", 1024, 250, 16384, "max", 250, 1),
                (4096, 1024, 0, 16384, "max", 0, 2),
                ("max", 4096, 0, 16384, 1024, 0, 2),
                ("max", 4096, 0, 16384, 2048, 1248, 1),
                ("max", 4096, 0, 512, "max", 0, 1)):
            with self.subTest(cap=cap, used=used, parent_cap=parent_cap):
                for directory, values in ((scope, (high, cap, used)),
                                          (part, (parent_high, parent_cap, parent_used))):
                    for name, value in zip(("memory.high", "memory.max", "memory.current"), values):
                        (directory / name).write_text("max" if value == "max" else str(value * 1024**2))
                    (directory / "memory.stat").write_text("file 0\n")
                with patch.dict(os.environ, {"AK_HOST_READINGS": ""}), \
                        patch.object(host, "PROC", proc), patch.object(host, "cpu_count", return_value=64):
                    readings = host.host_readings(cgroup_file=membership, cgroup_root=root,
                                                  slice_dir=part)
                self.assertEqual(gate.derived_heavy_limit(readings, running=0, unit=True), count)
                # Ordinary admission still reads the slice; a run cap bounds its pieces only.
                self.assertEqual(gate.derived_heavy_limit(readings, running=0),
                                 int((parent_high - parent_used) / gate.HEAVY_MEM_MB))
                without_slice = {key: value for key, value in readings.items()
                                 if not key.startswith("slice_")}
                self.assertEqual(gate.derived_heavy_limit(without_slice, running=0, unit=True), count)
                soft_room = parent_high - parent_used if high == "max" else high - used
                self.assertEqual(gate.derived_heavy_limit(without_slice, running=0),
                                 int(soft_room / gate.HEAVY_MEM_MB))
                for turn in ("", "0"):
                    with patch.dict(os.environ, {"AK_MAX_RUNS": turn,
                                                 "AK_HOST_READINGS": json.dumps(readings)}):
                        ok, text = self.check()
                    self.assertTrue(ok, text)
                    self.assertEqual(text.count("--- AK_SHARD="), count)

    def test_all_pieces_start_together_and_all_red_pieces_retry_alone(self):
        barrier, lock = threading.Barrier(2, timeout=3), threading.Lock()
        calls, active, reruns = Counter(), set(), []
        def limited(cmd, limit, env, output, **_kw):
            shard = env["AK_SHARD"]
            with lock:
                calls[shard] += 1
                attempt = calls[shard]
                active.add(shard)
                if attempt == 2:
                    reruns.append(set(active))
            if attempt == 1:
                barrier.wait()
            output.write(f"{'FAIL: under load' if attempt == 1 else 'passed'} {shard}\n".encode())
            with lock:
                active.remove(shard)
            return (1 if attempt == 1 else 0), "", False
        with patch.object(worker, "limited", side_effect=limited):
            ok, text = self.check()
        self.assertTrue(ok, text)
        self.assertEqual(calls, {"1/2": 2, "2/2": 2})
        self.assertEqual(reruns, [{"1/2"}, {"2/2"}])
        state = {}
        run.record_flakes(state, text)
        self.assertEqual(len(state["followups"]), 2)
        for shard in calls:
            self.assertIn(f"(AK_SHARD={shard}) failed, then passed on its re-run", text)
        self.assertEqual(len(list(self.run_dir.glob("gate-failed-*.log"))), 2)

    def test_a_second_failure_decides_only_that_piece_and_does_not_repeat_green_pieces(self):
        calls = Counter()
        def limited(cmd, limit, env, output, **_kw):
            shard = env["AK_SHARD"]
            calls[shard] += 1
            output.write(f"{'FAIL: broken' if shard == '2/2' else 'passed'}\n".encode())
            return int(shard == "2/2"), "", False
        with patch.object(worker, "limited", side_effect=limited):
            ok, text = self.check()
        self.assertFalse(ok)
        self.assertEqual(calls, {"1/2": 1, "2/2": 2})
        self.assertEqual(run.done_when_counts(text, [SUITE]), (0, 1))
        self.assertEqual(run.failing_checks(text), [[SUITE, "FAIL: broken"]])
        self.assertNotIn("flaky:", text)

    def test_a_red_first_piece_is_named_even_when_the_other_piece_passes_on_retry(self):
        calls = Counter()
        def limited(cmd, limit, env, output, **_kw):
            shard = env["AK_SHARD"]
            calls[shard] += 1
            code = int(shard == "1/2" or calls[shard] == 1)
            output.write(("FAIL: broken\n" if shard == "1/2" else
                          "FAIL: timing\n" if code else "passed\n").encode())
            return code, "", False
        with patch.object(worker, "limited", side_effect=limited):
            ok, text = self.check()
        self.assertFalse(ok)
        self.assertEqual(calls, {"1/2": 2, "2/2": 2})
        self.assertEqual(run.failing_checks(text), [[SUITE, "FAIL: broken"]])
        self.assertIn("FAIL: broken", run.first_failure(text))
        self.assertNotIn("FAIL: timing", run.first_failure(text))
        self.assertIn("flaky:", text)

    def test_a_busy_retry_repeats_only_its_piece_without_spending_another_retry(self):
        calls = Counter()
        def limited(cmd, limit, env, output, **_kw):
            shard = env["AK_SHARD"]
            calls[shard] += 1
            code = (1, 75, 0)[min(calls[shard] - 1, 2)] if shard == "2/2" else 0
            output.write(f"{'FAIL: timing' if code == 1 else 'busy' if code == 75 else 'passed'}\n".encode())
            return code, "", False
        with patch.object(worker, "limited", side_effect=limited), \
                patch.object(gate, "busy_turn", return_value=0) as busy:
            ok, text = self.check()
        self.assertTrue(ok, text)
        self.assertEqual(calls, {"1/2": 1, "2/2": 3})
        busy.assert_called_once()
        self.assertIn("flaky:", text)

    def test_a_silent_piece_cannot_borrow_its_siblings_output_or_be_retried(self):
        command = ('if test "$AK_SHARD" = 1/2; then sleep 3; '
                   'else while true; do echo active; sleep 0.02; done; fi')
        ok, text = self.check([command, "echo after"], silence=0.15)
        self.assertFalse(ok)
        self.assertIn("stopped after 0.0025 min of silence", text)
        self.assertIn("--- AK_SHARD=1/2 ---\n[killed at the limit]", text)
        self.assertNotIn("$ echo after", text)
        self.assertNotIn("flaky:", text)

    def test_each_piece_reserves_a_heavy_turn_and_retries_return_the_extra_turns(self):
        seen = []
        def limited(cmd, limit, env, **_kw):
            seen.append((env["AK_SHARD"], gate._heavy_running(), env.get("AK_HEAVY_TURN")))
            return (1 if len(seen) <= 2 else 0), "", False
        with patch.dict(os.environ, {"AK_MAX_RUNS": ""}), \
                patch.object(worker, "limited", side_effect=limited):
            (config.HOME / config.CONFIG_NAME).write_text("max_gates = 9\n")
            ok, text = self.check()
        self.assertTrue(ok, text)
        self.assertEqual([held for _, held, _ in seen], [2, 2, 1, 1])
        self.assertTrue(all(flag == "1" for _, _, flag in seen))
        self.assertEqual(gate._heavy_running(), 0)

    def test_isolated_cgroup_cost_is_saved_and_sizes_later_pieces(self):
        state = record.read_state(self.run_dir)
        record.save_state(self.run_dir, {**state, "scope": "acme"})
        with patch.object(host, "process_cgroup", return_value="/fixture/acme.scope"), \
                patch.object(host, "_slice_cpu_stat", side_effect=[
                    {"usage_usec": 0}, {"usage_usec": 40_000_000}]), \
                patch.object(host, "_scope_readings", side_effect=[
                    (1, 100 * 1024**2), (3, 2100 * 1024**2)]), \
                patch.object(gate.time, "monotonic", side_effect=[0, 10]):
            measured = gate._SuiteMeasure(self.run_dir)
            measured.sample()
            path, _, _ = gate.suite_cost(SUITE, self.root, self.run_dir)
            measured.save(path, 2)
        self.assertEqual(json.loads(path.read_text()), {"cpus": 2, "mem_mb": 1000})
        record.save_state(self.run_dir, state)
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps({
                **ROOM, "slice_memory_high_mb": 4000})}):
            ok, text = self.check()
        self.assertTrue(ok, text)
        self.assertEqual(text.count("--- AK_SHARD="), 2)
        path.write_text('{"cpus": 0, "mem_mb": "broken"}')
        self.assertTrue(self.check()[0])

    def test_target_probe_uses_the_same_pieces_and_retry(self):
        folder = self.root / "probe"
        folder.mkdir()
        _, _, wt = make_repos(folder)
        command = "true # AK_SHARD"
        lp, directory, _ = make_loop(folder, wt, [f"{command}  # once"])
        calls, original = Counter(), worker.limited
        def limited(cmd, limit, **kw):
            if cmd[0] != "bash":
                return original(cmd, limit, **kw)
            shard = kw["env"]["AK_SHARD"]
            calls[shard] += 1
            kw["output"].write(b"FAIL: on target\n" if shard == "2/2" else b"passed\n")
            return int(shard == "2/2"), "", False
        with patch.object(worker, "limited", side_effect=limited):
            note = run.target_fails(lp, "origin/main", f"$ {command}\n[exit 1]\nFAIL")
        self.assertIn("FAIL: on target", note)
        self.assertEqual(calls, {"1/2": 1, "2/2": 2})
        self.assertIn("--- AK_SHARD=2/2 ---", (directory / "target-probe.log").read_text())


if __name__ == "__main__":
    unittest.main()
