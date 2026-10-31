"""Run admission learns memory needs from finished runs; all readings and history are local."""

from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, history, host, record

NOW = 10 * 86400
PEAK = .56 * 1024
READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "cpus": 8,
            "slice_cpu_pressure": 14, "slice_memory_pressure": 0,
            "slice_memory_used_mb": 7.1 * 1024, "slice_memory_high_mb": 9.4 * 1024,
            "unit_limits": [(7.1 * 1024, 9.4 * 1024, 8 * 1024, "agentkit.slice")]}


class MemoryAdmissionByRoom(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix=".ak-test-memory-room-", dir=REPO)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.samples = 0
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        config.HOME.mkdir()
        config.RUNS.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AK_MAX_RUNS": "8", "AK_MIN_FREE_MB": "3072",
            "AK_HOST_READINGS": json.dumps(READINGS)}))
        os.environ.pop("AK_MAX_LOAD", None)
        self.stack.enter_context(patch.object(history.time, "time", return_value=NOW))
        self.stack.enter_context(patch.object(gate, "slot_counts", return_value=(7, 0, [])))
        self.stack.enter_context(patch.object(gate, "landing_waits", return_value=False))
        self.stack.enter_context(patch.object(record, "process_owner", return_value={"pid": 1}))
        # room, not pace: no poll's pause after each start, on a clock that stands still
        self.stack.enter_context(patch.object(gate, "SLOT_POLL", 0))
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute(history.SCHEMA)

    def measured(self, peak=PEAK, *, finished=NOW, state="pass", repo="acme"):
        self.samples += 1
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("INSERT INTO runs (run_id, repo, final_state, finished_at, peak_rss_mb) "
                       "VALUES (?,?,?,?,?)", (str(self.samples), repo, state, finished, peak))

    def claim(self, state, **readings):
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps({**READINGS, **readings})}):
            return gate.claim_slot(state, 8)

    def test_measured_run_fits_above_old_share(self):
        self.measured()
        state = {"run_id": "queued"}
        self.assertTrue(self.claim(state))
        self.assertEqual(state["state"], "running")

    def test_insufficient_room_holds_and_status_says_what_a_run_needs(self):
        self.measured()
        for first in (False, True):
            with self.subTest(first=first):
                state = {"run_id": "queued", "first": first}
                for _ in range(2):
                    self.assertFalse(self.claim(state, slice_memory_used_mb=9 * 1024))
                self.assertEqual(gate.slot_note(state),
                                 "waiting for the unit's memory · 0.4 G left, a run needs 0.6 G")
                self.assertEqual(state["slot_wait_kind"], "unit memory")
                self.assertTrue(self.claim(state))

    def test_room_equal_to_peak_admits(self):
        self.measured(512)
        state = {"run_id": "queued"}
        readings = {"slice_memory_used_mb": 512, "slice_memory_high_mb": 1024}
        self.assertTrue(self.claim(state, **readings))

    def test_admission_and_suites_use_the_same_memory_limit(self):
        self.measured()
        for overrides, holds, suites in (
                ({}, False, 5),
                ({"slice_memory_used_mb": 9 * 1024}, True, 1),
                ({"slice_memory_used_mb": None}, False, 4),
                ({"slice_memory_high_mb": None}, False, 4),
                ({"slice_memory_high_mb": -1}, False, 4),
                ({"slice_memory_used_mb": 0, "slice_memory_high_mb": 0}, True, 1),
                ({"slice_memory_high_mb": None, "unit_limits": []}, False, 8)):
            with self.subTest(overrides=overrides):
                readings = {**READINGS, "unit_limits": [(PEAK, 2048 + PEAK)], **overrides}
                reason, _ = gate._wait_reason(readings, 3072, 0, PEAK)
                self.assertEqual(reason is not None, holds)
                self.assertEqual(gate.derived_heavy_limit(readings, running=1,
                                                          job_mem_mb=PEAK), suites)

    def test_pressure_past_its_limit_holds_with_room_and_with_or_without_measurements(self):
        for measured in (False, True):
            if measured:
                self.measured()
            for first in (False, True):
                with self.subTest(measured=measured, first=first):
                    state = {"run_id": "queued", "first": first}
                    self.assertFalse(self.claim(state, slice_memory_pressure=10.5))
                    self.assertFalse(self.claim(state, slice_memory_pressure=10.5))
                    self.assertEqual(gate.slot_note(state),
                                     "waiting for ak's memory · pressure 10.5%, limit 10%")

    def test_pages_coming_back_from_swap_hold_no_run_with_room(self):
        # Idle seats paging back in kept the slice at 0.01 to 1.2% on 17 Oct, with 4.3 G of room.
        self.measured()
        for pressure in (.01, 1.2, 10):
            with self.subTest(pressure=pressure):
                state = {"run_id": "queued"}
                self.assertTrue(self.claim(state, slice_memory_pressure=pressure))

    def test_no_measurements_keep_old_share(self):
        state = {"run_id": "queued"}
        self.assertFalse(self.claim(state))
        self.assertEqual(state["slot_wait_kind"], "unit memory")
        self.assertEqual(gate.slot_note(state), "waiting for the unit's memory · 7.1 of 9.4 G")
        readings = {"slice_memory_used_mb": 9.4 * 1024 * .75}
        self.assertTrue(self.claim(state, **readings))

    def test_recent_finished_positive_peaks_supply_the_median(self):
        for peak in (PEAK / 2, PEAK, PEAK * 2):
            self.measured(peak)
        for peak in (None, 0, -100, float("inf")):
            self.measured(peak)
        self.measured(90000, finished=NOW - 7 * 86400 - 1)
        self.measured(90000, finished=None, state="running")
        self.measured(90000, finished=NOW + 1)
        self.measured(90000, state="stopped")
        self.measured(90000, repo="agentkit-smoke")
        before = history.path().read_bytes()
        self.assertEqual(history.recent_peak_rss_mb(), PEAK)
        self.assertEqual(history.path().read_bytes(), before)
        state = {"run_id": "queued"}
        self.assertTrue(self.claim(state))

    def test_missing_unreadable_or_unmeasured_history_keeps_old_share(self):
        self.measured(None)
        self.measured(0)
        self.measured(PEAK, finished=NOW - 7 * 86400 - 1)
        self.assertIsNone(history.recent_peak_rss_mb())
        for contents in (None, "unreadable database"):
            history.path().unlink(missing_ok=True)
            if contents is not None:
                history.path().write_text(contents)
            state = {"run_id": "queued"}
            self.assertFalse(self.claim(state))
            self.assertEqual(state["slot_wait_kind"], "unit memory")

    def test_host_reads_slice_memory_pressure_and_excludes_cache(self):
        proc = self.root / "proc"
        proc.mkdir()
        cgroup = self.root / "cgroup"
        slice_dir = cgroup / "agentkit.slice"
        slice_dir.mkdir(parents=True)
        cgroup_file = proc / "cgroup"
        cgroup_file.write_text("0::/agentkit.slice\n")
        (slice_dir / "memory.high").write_text(str(10 * 1024 ** 3))
        (slice_dir / "memory.current").write_text(str(8 * 1024 ** 3))
        (slice_dir / "memory.stat").write_text(f"inactive_file {1024 ** 3}\n")
        pressure = slice_dir / "memory.pressure"
        pressure.write_text("some avg10=0.03 avg60=0.02 total=10\nfull avg10=0.01\n")
        with patch.dict(os.environ), patch.object(host, "PROC", proc):
            os.environ.pop("AK_HOST_READINGS", None)
            readings = host.host_readings(cgroup_file=cgroup_file, cgroup_root=cgroup,
                                          slice_dir=slice_dir)
        self.assertEqual(readings["slice_memory_pressure"], .03)
        self.assertEqual(readings["slice_memory_used_mb"], 7 * 1024)
        self.assertEqual(readings["slice_memory_high_mb"], 10 * 1024)
        pressure.write_text("some avg10=invalid\n")
        self.assertIsNone(host._slice_pressure(slice_dir, "memory"))
        pressure.unlink()
        self.assertIsNone(host._slice_pressure(slice_dir, "memory"))


if __name__ == "__main__":
    unittest.main()
