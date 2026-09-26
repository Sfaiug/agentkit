"""A run the host has frozen still counts against admission.

Seven frozen runs hold the load gate shut at load 2 of 8; the wait names them,
the thaw admits as usual, and `--first` ignores them with the rest of the load.
Offline: a throwaway HOME, fake run records, a fake /proc and cgroup tree, and
injected host readings. No real process is frozen, signalled or read.
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, watch  # noqa: E402

HEALTHY = {"free_mb": 4096, "mem_total_mb": 16384, "load": 2, "cpus": 8,
           "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}
FAKE_OWNER = {"pid": 999999, "process_identity": {"boot": "test", "ticks": 1}}


class FrozenAdmission(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".frozen-admission-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AGENTKIT_SESSION": "",
            "AK_MAX_RUNS": "32", "AK_MIN_FREE_MB": "3072", "AK_MAX_LOAD": "8",
            "AK_HOST_READINGS": json.dumps(HEALTHY)}))
        config.RUNS.mkdir(parents=True)
        config.HOME.mkdir(exist_ok=True)
        # every pid here is a fake: aliveness is said, never asked, and the only
        # cgroups read are the test's own
        self.stack.enter_context(patch.object(run, "process_active", return_value=True))
        self.stack.enter_context(patch.object(run, "process_owner",
                                              return_value=dict(FAKE_OWNER)))
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(watch, "PROC", self.proc))
        self.cgroup = self.root / "cgroup"
        self.cgroup.mkdir()
        self.stack.enter_context(patch.object(orch, "CGROUP_ROOT", self.cgroup))

    def freeze(self, name, pid, held=True):
        """A running run record whose process the (fake) host holds, or not."""
        (self.proc / str(pid)).mkdir(parents=True, exist_ok=True)
        (self.proc / str(pid) / "cgroup").write_text(f"0::/frozen-test/{name}\n")
        leaf = self.cgroup / "frozen-test" / name
        leaf.mkdir(parents=True, exist_ok=True)
        (leaf / "cgroup.freeze").write_text("1\n" if held else "0\n")
        directory = config.RUNS / name
        directory.mkdir()
        run.save_state(directory, {"run_id": name, "state": "running",
                                   "run_depth": 0, **FAKE_OWNER, "pid": pid})
        return directory

    def thaw(self, name):
        (self.cgroup / "frozen-test" / name / "cgroup.freeze").write_text("0\n")

    def queued(self, name, first=False):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "state": "queued", "slot_waiting": True,
                 "queued_at": 1000, "run_depth": 0, **FAKE_OWNER}
        if first:
            state["first"] = True
        run.save_state(directory, state)
        return directory

    def hold(self, count=7):
        for n in range(count):
            self.freeze(f"20250925-120{n}-held", 50001 + n)

    def test_frozen_runs_hold_the_load_gate(self):
        self.hold(7)
        state = run.read_state(self.queued("20250925-1300-waiter"))
        self.assertFalse(run.claim_slot(state, 32))
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for the host to calm · load 2 + 7 frozen runs, limit 8")
        self.assertEqual(state["slot_wait_kind"], "load")

    def test_thawed_runs_admit_as_usual(self):
        self.hold(7)
        state = run.read_state(self.queued("20250925-1300-waiter"))
        self.assertFalse(run.claim_slot(state, 32))
        self.assertEqual(state["slot_wait_kind"], "load")
        for n in range(7):
            self.thaw(f"20250925-120{n}-held")
        self.assertFalse(run.claim_slot(state, 32))  # first steady poll
        self.assertTrue(run.claim_slot(state, 32))
        self.assertEqual(state["state"], "running")

    def test_first_ignores_frozen_runs(self):
        self.hold(7)
        state = run.read_state(self.queued("20250925-1300-first", first=True))
        self.assertFalse(run.claim_slot(state, 32))  # first steady poll
        self.assertNotIn("slot_wait_kind", state)
        self.assertTrue(run.claim_slot(state, 32))
        self.assertEqual(state["state"], "running")

    def test_one_frozen_run_reads_singular(self):
        self.hold(1)
        with patch.dict(os.environ,
                        {"AK_HOST_READINGS": json.dumps({**HEALTHY, "load": 8})}):
            state = run.read_state(self.queued("20250925-1300-waiter"))
            self.assertFalse(run.claim_slot(state, 32))
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for the host to calm · load 8 + 1 frozen run, limit 8")

    def test_load_past_the_limit_says_so_already(self):
        self.hold(7)
        with patch.dict(os.environ,
                        {"AK_HOST_READINGS": json.dumps({**HEALTHY, "load": 41})}):
            state = run.read_state(self.queued("20250925-1300-waiter"))
            self.assertFalse(run.claim_slot(state, 32))
        self.assertEqual(state["slot_wait_reason"],
                         "waiting for the host to calm · load 41, limit 8")


if __name__ == "__main__":
    unittest.main()
