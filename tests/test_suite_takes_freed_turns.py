"""A sharded suite splits into the pieces the host's full derived limit fits, and its pieces
take turns freed after it starts.

Offline: temporary HOME, fake turn files under it, injected host readings, a fake box.
"""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, gate, gitcall, host, worker
from agentkit import record

# 4 cores and 1.7 GB: four pieces at 0.7 core and 0.41 GB each.
ROOM = {"cpus": 4, "load": 0, "free_mb": 1700, "slice_cpu_quota": 4, "slice_cpu_used": 0,
        "slice_memory_high_mb": 1700, "slice_memory_used_mb": 0}
SUITE = 'echo "${AK_SHARD}"'


class SuiteTakesFreedTurns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-freed-turns-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "", "AK_HOST_READINGS": json.dumps(ROOM),
            "AK_CGROUP_FILE": str(self.root / "no-cgroup"),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(gitcall, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(gate, "_running_commands", return_value=["fixture"]))
        self.stack.enter_context(patch.object(gate, "GATE_POLL", 0.01))
        self.stack.enter_context(patch.object(gate, "_run_readings", self.readings))
        self.stack.enter_context(patch.object(worker, "boxed", side_effect=self.boxed))
        self.on_start, self.together = {}, 1
        self.lock = threading.Lock()
        self.running, self.peak, self.held, self.shards = 0, 0, [], []
        self.started = threading.Condition(self.lock)
        self.holders = []

    def readings(self):
        """The fake host: each held turn's piece uses its share of the room."""
        held = gate._heavy_running()
        return {**ROOM, "slice_cpu_used": 0.7 * held, "slice_memory_used_mb": 410 * held}

    def hold_others(self, count):
        """The fake host's other suites: turns locked on files this test opened itself."""
        for index in range(count):
            holder = gate.gate_lock(None, index).open("a")
            fcntl.flock(holder, fcntl.LOCK_EX)
            self.holders.append(holder)
            self.addCleanup(holder.close)

    def free_others(self):
        for holder in self.holders:
            fcntl.flock(holder, fcntl.LOCK_UN)

    def boxed(self, cmd, limit, env, activity, **_kw):
        """A piece, of the run whose directory holds its log; it waits up to 5 s for
        `together` pieces running."""
        name = Path(activity).parent.name
        with self.started:
            self.running += 1
            self.peak = max(self.peak, self.running)
            self.held.append(gate._heavy_running())
            self.shards.append((name, env["AK_SHARD"]))
            self.started.notify_all()
        self.on_start.pop(name, lambda: None)()
        with self.started:
            self.started.wait_for(lambda: self.running >= self.together, timeout=5)
        time.sleep(0.05)
        with self.started:
            self.running -= 1
        return 0, "", False

    def suite(self, name):
        run_dir = config.RUNS / name
        run_dir.mkdir()
        record.save_state(run_dir, {
            "run_id": name, "state": "running", "repo": str(self.root), "round_summaries": [],
            "pid": os.getpid(), "process_identity": host.process_identity(os.getpid())})
        return gate.run_done_when([SUITE], self.root, run_dir / "gate.log", set(),
                                  limit=60, log=lambda line: None, run_dir=run_dir)

    def test_a_suite_admitted_on_one_free_turn_runs_pieces_on_turns_freed_after(self):
        self.hold_others(3)
        self.on_start["acme"], self.together = self.free_others, 2
        ok, text = self.suite("acme")
        self.assertTrue(ok, text)
        self.assertEqual(sorted(shard for _, shard in self.shards), ["1/4", "2/4", "3/4", "4/4"])
        self.assertGreater(self.peak, 1)
        self.assertEqual(self.held[0], 4)
        self.assertEqual(gate._heavy_running(), 0)

    def test_a_suite_on_an_idle_host_is_split_and_started_as_today(self):
        self.together = 4
        ok, text = self.suite("acme")
        self.assertTrue(ok, text)
        self.assertEqual(sorted(shard for _, shard in self.shards), ["1/4", "2/4", "3/4", "4/4"])
        self.assertEqual(self.peak, 4)
        self.assertEqual(self.held, [4, 4, 4, 4])

    def test_turns_held_never_exceed_the_limit_while_two_suites_pieces_wait(self):
        self.hold_others(3)
        first = threading.Event()
        results = {}
        self.on_start["acme"] = first.set
        acme = threading.Thread(target=lambda: results.update(acme=self.suite("acme")))
        acme.start()
        self.assertTrue(first.wait(10))
        widget = threading.Thread(target=lambda: results.update(widget=self.suite("widget")))
        widget.start()
        # widget waits for its first turn, acme's other pieces for theirs at acme's place
        waits = {}
        for _ in range(1000):
            waits = {name: (record.read_state(config.RUNS / name) or {}).get("gate_turn")
                     for name in ("acme", "widget")}
            if all(waits.values()):
                break
            time.sleep(0.01)
        self.assertLess(waits["acme"]["since"], waits["widget"]["since"])
        self.assertTrue(gate._gate_waiter_before(None, "widget", waits["widget"]["since"]))
        self.free_others()
        acme.join(30)
        widget.join(30)
        self.assertEqual({name: ok for name, (ok, _) in results.items()},
                         {"acme": True, "widget": True})
        self.assertLessEqual(max(self.held), 4)
        self.assertEqual(sorted(self.shards), [(name, f"{index}/4") for name in ("acme", "widget")
                                               for index in range(1, 5)])
        # acme waited first: all its pieces start before any of widget's
        self.assertEqual([name for name, _ in self.shards[:4]], ["acme"] * 4)
        self.assertEqual(gate._heavy_running(), 0)


if __name__ == "__main__":
    unittest.main()
