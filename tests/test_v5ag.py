"""v5ag: the tick uses the shared silence window, ignoring retired time keys.

Offline and deterministic: fake run directories under a temporary HOME with fake
`ak run` process trees, reusing tests/test_v5x.py's builders. No tmux beyond
`agentkit-test`, no webhook, no model calls.
"""

import json
import time
import unittest
from pathlib import Path

import test_v5x as _v5x
from agentkit import watch


class V5AG(unittest.TestCase):
    # Isolation, process trees and run records are V5X's builders, reused here;
    # this file adds only a harmless gate fixture and recorded-limit support.
    def setUp(self):
        _v5x.V5X.setUp(self)

    def kill_procs(self):
        return _v5x.V5X.kill_procs(self)

    def spawn_loop(self, child_argv):
        return _v5x.V5X.spawn_loop(self, child_argv)

    def spawn_worker(self, reviewer=False):
        return _v5x.V5X.spawn_worker(self, reviewer=reviewer)

    def gate_sleep(self):
        """A harmless done-when gate: a `bash -c` shell kept alive by a sleeping child."""
        # `wait` keeps the shell from exec-optimizing into its only child, so the
        # step keeps its `bash -c` shape and a two-process tree to terminate.
        return ["bash", "-c", "sleep 1000 & wait"]

    def gate_tree(self, pid):
        """The gate child's pids with its live descendant; asserts the tree shape."""
        pairs = watch.loop_children(pid)
        self.assertTrue(pairs, "fake loop should have a gate child")
        child, argv = sorted(pairs, key=lambda pair: pair[0])[0]
        self.assertEqual(Path(argv[0]).name, "bash")
        self.assertEqual(argv[1:2], ["-c"], "the gate step must keep its `bash -c` shape")
        tree = watch.descendants(child)
        self.assertGreater(len(tree), 1, "the gate shell must hold a live descendant")
        return [child], tree

    def make_run(self, run_id, *args, done_when=None, **kwargs):
        """V5X.make_run plus the recorded done-when limit this change reads."""
        run_dir, state = _v5x.V5X.make_run(self, run_id, *args, **kwargs)
        if done_when is not None:
            state["done_when_minutes"] = done_when
            (run_dir / "run.json").write_text(json.dumps(state, indent=2))
        return run_dir, state

    def age_run(self, run_dir, minutes):
        return _v5x.V5X.age_run(self, run_dir, minutes)

    def read_state(self, run_dir):
        return _v5x.V5X.read_state(self, run_dir)

    def child_pids(self, pid):
        return _v5x.V5X.child_pids(self, pid)

    def test_v5ag_gate_90_untouched_at_19(self):
        parent = self.spawn_loop(self.gate_sleep())
        run_dir, _ = self.make_run("20260916-0000-v5ag-a", pid=parent.pid, done_when=90)
        children, _ = self.gate_tree(parent.pid)
        self.age_run(run_dir, 19)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(state.get("stalls") or [], [])
        self.assertNotIn("stall:", (run_dir / "log.txt").read_text())
        self.assertFalse(watch._gone(children[0]), "a gate the loop still allows is never struck")
        self.assertFalse(watch._gone(parent.pid))
        self.assertEqual(self.resumed, [])

    def test_v5ag_gate_90_fires_at_21_with_20(self):
        parent = self.spawn_loop(self.gate_sleep())
        run_dir, _ = self.make_run("20260916-0000-v5ag-b", pid=parent.pid, done_when=90)
        children, grandchild = self.gate_tree(parent.pid)
        self.age_run(run_dir, 21)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 1)
        self.assertEqual(state["stalls"][0]["action"], "killed step")
        text = (run_dir / "log.txt").read_text()
        self.assertIn("stall: no output for 20 min in round 2", text)
        for member in grandchild:
            self.assertTrue(watch._gone(member), f"{member} should be gone")
        self.assertFalse(watch._gone(parent.pid), "the loop itself must live on")

    def test_v5ag_gate_without_limit_fires_at_21_with_20(self):
        parent = self.spawn_loop(self.gate_sleep())
        run_dir, _ = self.make_run("20260916-0000-v5ag-c", pid=parent.pid)
        children, tree = self.gate_tree(parent.pid)
        self.age_run(run_dir, 21)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 1)
        text = (run_dir / "log.txt").read_text()
        self.assertIn("stall: no output for 20 min in round 2", text)
        for member in tree:
            self.assertTrue(watch._gone(member), f"{member} should be gone")
        self.assertFalse(watch._gone(parent.pid), "the loop itself must live on")

    def test_v5ag_worker_90_fires_at_21_with_20(self):
        parent = self.spawn_worker()
        children = self.child_pids(parent.pid)
        self.assertTrue(children, "fake loop should have a worker child")
        tree = watch.descendants(children[0])
        run_dir, _ = self.make_run("20260916-0000-v5ag-d", pid=parent.pid, done_when=90)
        self.age_run(run_dir, 21)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state.get("stalls") or []), 1)
        text = (run_dir / "log.txt").read_text()
        self.assertIn("stall: no output for 20 min in round 2", text)
        self.assertIn("worker:", state["stalls"][0]["step"])
        for member in tree:
            self.assertTrue(watch._gone(member), f"{member} should be gone")
        self.assertFalse(watch._gone(parent.pid), "the loop itself must live on")

    def test_v5ag_stall_240_and_gate_90_are_ignored_at_21(self):
        parent = self.spawn_loop(self.gate_sleep())
        run_dir, _ = self.make_run("20260916-0000-v5ag-e", pid=parent.pid,
                                   minutes=240, done_when=90)
        children, _ = self.gate_tree(parent.pid)
        self.age_run(run_dir, 21)
        watch.recover_runs({}, dry_run=False, log=self.logs.append, now=time.time())
        state = self.read_state(run_dir)
        self.assertEqual(len(state["stalls"]), 1)
        self.assertIn("stall:", (run_dir / "log.txt").read_text())
        self.assertTrue(watch._gone(children[0]))
        self.assertFalse(watch._gone(parent.pid))

    def test_v5ag_dry_run_reports_20_and_touches_nothing(self):
        parent = self.spawn_loop(self.gate_sleep())
        run_dir, _ = self.make_run("20260916-0000-v5ag-f", pid=parent.pid, done_when=90)
        children, _ = self.gate_tree(parent.pid)
        self.age_run(run_dir, 21)
        before = (run_dir / "log.txt").read_text()
        watch.recover_runs({}, dry_run=True, log=self.logs.append, now=time.time())
        self.assertTrue(any("would kill the step" in line and "20 min" in line
                            for line in self.logs),
                        f"dry-run must name the 20 min allowance: {self.logs}")
        self.assertFalse(watch._gone(children[0]), "dry-run touches nothing")
        self.assertFalse(watch._gone(parent.pid))
        self.assertEqual(self.read_state(run_dir).get("stalls") or [], [])
        self.assertEqual((run_dir / "log.txt").read_text(), before)
        self.assertEqual(self.resumed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
