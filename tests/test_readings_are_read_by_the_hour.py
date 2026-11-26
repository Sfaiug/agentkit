"""A machine's kept readings are read back by the hour, oldest first, ending at a given time.

Temporary HOME, invented machine names and readings written through `readings.keep` (plus raw
corrupt lines for the skip rules).  Nothing reads the wall clock.
"""

import calendar
import json
import math
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, machines, readings  # noqa: E402

HOUR = 3600
# 2026-11-26 00:00:00 UTC: lets a four-hour window cross two UTC day files (Nov 25 and Nov 26).
MIDNIGHT = calendar.timegm((2026, 11, 26, 0, 0, 0, 0, 0, 0))


def reading(load, cores=4, memory_mb=1000, free_mb=250):
    return {"system": "Linux", "processor": "x86_64", "cores": cores,
            "memory_mb": memory_mb, "free_mb": free_mb, "load": load,
            "disk_free_mb": 50000, "battery": 0, "power": 1}


class ReadingsByTheHour(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-readings-hours-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / "state").mkdir()
        home = patch.object(config, "HOME", self.home)
        home.start()
        self.addCleanup(home.stop)
        host = patch.object(socket, "gethostname", return_value="acme-home")
        host.start()
        self.addCleanup(host.stop)
        self.folder = self.home / "state" / "readings"

    def test_reads_home_and_listed_machine_across_two_days_with_gap_and_broken_line(self):
        # Window: [MIDNIGHT - 3600, MIDNIGHT + 3 * 3600) -> 4 hours spanning Nov 25 and Nov 26.
        # Hour 0 (23:00 Nov 25): two readings for home, one for acme-linux.
        readings.keep(MIDNIGHT - 3000, {
            machines.HERE: reading(load=2.0, cores=4, memory_mb=1000, free_mb=500),
            "acme-linux": reading(load=8.0, cores=8, memory_mb=2000, free_mb=1000),
        })
        readings.keep(MIDNIGHT - 600, {
            machines.HERE: reading(load=6.0, cores=4, memory_mb=1000, free_mb=300),
        })
        # Hour 1 (00:00 Nov 26): one reading for acme-linux only (gap for home).
        readings.keep(MIDNIGHT + 120, {
            "acme-linux": reading(load=0.0, cores=4, memory_mb=1000, free_mb=1000),
        })
        # Invalid UTF-8 line and a torn trailing write without a newline (which the next keep's
        # leading newline terminates), right before hour 3's valid reading.
        day2 = self.folder / "2026-11-26.jsonl"
        with day2.open("ab") as file:
            file.write(b'\xff\xfe{"at": 1795651300, "home": "acme-home"}\n'
                       b'{"at": 1795651300, "home": "acme-home", "cor')
        # Hour 2 (01:00 Nov 26): gap for both.
        # Hour 3 (02:00 Nov 26): one reading for home, two for acme-linux.
        readings.keep(MIDNIGHT + 2 * HOUR + 30, {
            machines.HERE: reading(load=1.0, cores=2, memory_mb=1000, free_mb=0),
            "acme-linux": reading(load=3.0, cores=2, memory_mb=1000, free_mb=200),
        })
        readings.keep(MIDNIGHT + 2 * HOUR + 900, {
            "acme-linux": reading(load=1.0, cores=2, memory_mb=1000, free_mb=600),
        })

        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["2026-11-25.jsonl", "2026-11-26.jsonl"])

        until = MIDNIGHT + 3 * HOUR
        home_hours = readings.hours("acme-home", until, 4, home=True)
        self.assertEqual([h.start for h in home_hours],
                         [MIDNIGHT - HOUR, MIDNIGHT, MIDNIGHT + HOUR, MIDNIGHT + 2 * HOUR])
        self.assertAlmostEqual(home_hours[0].processors, 1.0)
        self.assertAlmostEqual(home_hours[0].memory, 0.6)
        self.assertIsNone(home_hours[1].processors)
        self.assertIsNone(home_hours[1].memory)
        self.assertIsNone(home_hours[2].processors)
        self.assertIsNone(home_hours[2].memory)
        self.assertAlmostEqual(home_hours[3].processors, 0.5)
        self.assertAlmostEqual(home_hours[3].memory, 1.0)

        linux_hours = readings.hours("acme-linux", until, 4, home=False)
        self.assertEqual([h.start for h in linux_hours],
                         [MIDNIGHT - HOUR, MIDNIGHT, MIDNIGHT + HOUR, MIDNIGHT + 2 * HOUR])
        self.assertAlmostEqual(linux_hours[0].processors, 1.0)
        self.assertAlmostEqual(linux_hours[0].memory, 0.5)
        # Zero load and zero memory in use are 0.0, distinct from a gap's None.
        self.assertEqual(linux_hours[1].processors, 0.0)
        self.assertEqual(linux_hours[1].memory, 0.0)
        self.assertIsNone(linux_hours[2].processors)
        self.assertIsNone(linux_hours[2].memory)
        self.assertAlmostEqual(linux_hours[3].processors, 1.0)
        self.assertAlmostEqual(linux_hours[3].memory, 0.6)

    def test_home_and_listed_machine_with_same_name_are_never_pooled(self):
        readings.keep(MIDNIGHT + 10, {
            machines.HERE: reading(load=4.0, cores=4, memory_mb=1000, free_mb=200),
            "acme-home": reading(load=1.0, cores=4, memory_mb=1000, free_mb=800),
        })
        # A malformed line naming both is ignored by both.
        with (self.folder / "2026-11-26.jsonl").open("a") as file:
            file.write(json.dumps({"at": MIDNIGHT + 20, "home": "acme-home",
                                   "machine": "acme-home", "load": 99.0, "cores": 1,
                                   "memory_mb": 1000, "free_mb": 0}) + "\n")

        [as_home] = readings.hours("acme-home", MIDNIGHT + HOUR, 1, home=True)
        [as_listed] = readings.hours("acme-home", MIDNIGHT + HOUR, 1, home=False)
        self.assertAlmostEqual(as_home.processors, 1.0)
        self.assertAlmostEqual(as_home.memory, 0.8)
        self.assertAlmostEqual(as_listed.processors, 0.25)
        self.assertAlmostEqual(as_listed.memory, 0.2)

    def test_hour_edges_are_start_inclusive_and_end_exclusive_down_to_one_ulp(self):
        start = MIDNIGHT
        mid = MIDNIGHT + HOUR
        until = MIDNIGHT + 2 * HOUR
        self.folder.mkdir(parents=True)
        entries = [
            (math.nextafter(float(start), -math.inf), 99.0),  # just before window -> out
            (float(start), 1.0),                              # exact start -> hour 0
            (math.nextafter(float(mid), -math.inf), 3.0),     # just before mid -> hour 0
            (float(mid), 5.0),                                # exact mid -> hour 1
            (math.nextafter(float(until), -math.inf), 7.0),   # just before until -> hour 1
            (float(until), 99.0),                             # exact until -> out
            (math.nextafter(float(until), math.inf), 99.0),   # just after until -> out
        ]
        with (self.folder / "2026-11-26.jsonl").open("w") as file:
            for at, load in entries:
                file.write(json.dumps({"at": at, "machine": "acme-edge",
                                       **reading(load=load, cores=1)}) + "\n")

        got = readings.hours("acme-edge", until, 2, home=False)
        self.assertAlmostEqual(got[0].processors, 2.0)
        self.assertAlmostEqual(got[1].processors, 6.0)

    def test_running_mean_stays_finite_for_huge_loads(self):
        self.folder.mkdir(parents=True)
        with (self.folder / "2026-11-26.jsonl").open("w") as file:
            for offset, load in ((10, 1e308), (20, 1e308)):
                file.write(json.dumps({"at": MIDNIGHT + offset, "machine": "acme-big",
                                       "load": load, "cores": 1,
                                       "memory_mb": 1e308, "free_mb": 0}) + "\n")
            for offset, load in ((HOUR + 10, 1e308), (HOUR + 20, 0.0)):
                file.write(json.dumps({"at": MIDNIGHT + offset, "machine": "acme-big",
                                       "load": load, "cores": 1,
                                       "memory_mb": 1000, "free_mb": 1000}) + "\n")

        got = readings.hours("acme-big", MIDNIGHT + 2 * HOUR, 2, home=False)
        self.assertTrue(math.isfinite(got[0].processors))
        self.assertEqual(got[0].processors, 1e308)
        self.assertEqual(got[0].memory, 1.0)
        self.assertTrue(math.isfinite(got[1].processors))
        self.assertEqual(got[1].processors, 5e307)
        self.assertEqual(got[1].memory, 0.0)

    def test_extreme_years_and_epoch_compute_no_calendar_date(self):
        self.folder.mkdir(parents=True)
        year_9999 = 253402300799     # 9999-12-31 23:59:59 UTC
        with (self.folder / "1970-01-01.jsonl").open("w") as file:
            file.write(json.dumps({"at": 0, "machine": "acme-time",
                                   **reading(load=2.0, cores=2, memory_mb=100, free_mb=25)}) + "\n")
            file.write(json.dumps({"at": year_9999, "machine": "acme-time",
                                   **reading(load=4.0, cores=2, memory_mb=100, free_mb=50)}) + "\n")

        # Year 1 (negative epoch): no date error, all empty.
        year_1 = readings.hours("acme-time", -62135596800, 3, home=False)
        self.assertEqual(len(year_1), 3)
        self.assertTrue(all(h.processors is None and h.memory is None for h in year_1))

        # Window straddling 0: [-3600, 0) empty, [0, 3600) holds at=0.
        epoch = readings.hours("acme-time", HOUR, 2, home=False)
        self.assertIsNone(epoch[0].processors)
        self.assertAlmostEqual(epoch[1].processors, 1.0)
        self.assertAlmostEqual(epoch[1].memory, 0.75)

        # Window ending past year 9999 (start of year 10000): finds at=year_9999 without date math.
        far = readings.hours("acme-time", year_9999 + 1, 2, home=False)
        self.assertIsNone(far[0].processors)
        self.assertAlmostEqual(far[1].processors, 2.0)
        self.assertAlmostEqual(far[1].memory, 0.5)

    def test_skips_unusable_lines_non_day_files_and_unreadable_files(self):
        self.folder.mkdir(parents=True)
        at = MIDNIGHT + 10
        bad_lines = [
            "not json",
            "[1, 2, 3]",
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100}}',
            f'{{"at": true, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": false, "cores": 2, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": true, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": true, "free_mb": 0}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100, "free_mb": false}}',
            '{"at": -1, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100, "free_mb": 50}',
            f'{{"at": {at}, "machine": "acme-bad", "load": -0.1, "cores": 2, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": 0.5, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 0.5, "free_mb": 0}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100, "free_mb": -1}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100, "free_mb": 101}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": NaN, "cores": 2, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": Infinity, "cores": 2, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": {"9" * 400}, "cores": 2, "memory_mb": 100, "free_mb": 50}}',
            f'{{"at": {at}, "machine": "acme-bad", "load": "1", "cores": 2, "memory_mb": 100, "free_mb": 50}}',
        ]
        good = json.dumps({"at": at, "machine": "acme-bad",
                           **reading(load=2.0, cores=4, memory_mb=100, free_mb=50)})
        (self.folder / "2026-11-26.jsonl").write_text("\n".join([*bad_lines, good]) + "\n")
        # Non-day files are never read.
        (self.folder / "acme.jsonl").write_text(
            json.dumps({"at": MIDNIGHT + 20, "machine": "acme-bad",
                        **reading(load=99.0, cores=1, memory_mb=100, free_mb=0)}) + "\n")
        # A directory named like a day file cannot be opened as a file and is skipped.
        (self.folder / "2026-11-25.jsonl").mkdir()

        [got] = readings.hours("acme-bad", MIDNIGHT + HOUR, 1, home=False)
        self.assertAlmostEqual(got.processors, 0.5)
        self.assertAlmostEqual(got.memory, 0.5)

        if os.geteuid() != 0:
            locked = self.folder / "2026-11-24.jsonl"
            locked.write_text(good + "\n")
            locked.chmod(0)
            self.addCleanup(lambda: locked.chmod(0o600))
            [still] = readings.hours("acme-bad", MIDNIGHT + HOUR, 1, home=False)
            self.assertAlmostEqual(still.processors, 0.5)

    def test_missing_folder_zero_count_and_invalid_arguments(self):
        # Missing folder returns empty entries.
        empty = readings.hours("acme-none", MIDNIGHT + HOUR, 2, home=False)
        self.assertEqual(empty, [readings.Hour(MIDNIGHT - HOUR, None, None),
                                 readings.Hour(MIDNIGHT, None, None)])
        self.assertEqual(readings.hours("acme-none", MIDNIGHT, 0, home=True), [])

        with self.assertRaises(ValueError):
            readings.hours("acme-none", MIDNIGHT, -1, home=False)
        for bad_call in (
            lambda: readings.hours(123, MIDNIGHT, 1, home=False),
            lambda: readings.hours("acme", MIDNIGHT, 1, home="machine"),
            lambda: readings.hours("acme", MIDNIGHT + 0.5, 1, home=False),
            lambda: readings.hours("acme", True, 1, home=False),
            lambda: readings.hours("acme", MIDNIGHT, True, home=False),
            lambda: readings.hours("acme", MIDNIGHT, 1.5, home=False),
        ):
            with self.assertRaises(TypeError):
                bad_call()


if __name__ == "__main__":
    unittest.main()
