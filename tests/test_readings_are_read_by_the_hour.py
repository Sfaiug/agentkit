"""A machine's kept readings are read back by the hour, oldest first, ending at a given time.

Temporary HOME, invented machine names and readings written through `readings.keep` (plus raw
lines for the skip rules).  One table of cases, one per rule, run through one helper; nothing
reads the clock.
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

H = 3600
# 2026-11-26 00:00:00 UTC: a four-hour window crosses two UTC day files (Nov 25 and Nov 26).
M = calendar.timegm((2026, 11, 26, 0, 0, 0, 0, 0, 0))
YEAR_9999 = 253402300799
HERE = machines.HERE


def r(load, cores=4, memory_mb=1000, free_mb=250):
    return {"system": "Linux", "processor": "x86_64", "cores": cores, "memory_mb": memory_mb,
            "free_mb": free_mb, "load": load, "disk_free_mb": 50000, "battery": 0, "power": 1}


def raw(at, who, load=1.0, cores=2, memory_mb=100, free_mb=50):
    tag = {"machine": who} if isinstance(who, str) else who
    return (json.dumps({"at": at, **tag, "load": load, "cores": cores,
                        "memory_mb": memory_mb, "free_mb": free_mb}) + "\n").encode()


def bad_lines():
    at = M + 10
    base = {"at": at, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100, "free_mb": 50}
    head = f'{{"at": {at}, "machine": "acme-bad", "cores": 2, "memory_mb": 100, "free_mb": 50, "load": '
    bad = ({"at": True}, {"load": False}, {"cores": True}, {"memory_mb": True}, {"free_mb": False},
           {"at": -1}, {"load": -0.1}, {"cores": 0.5}, {"memory_mb": 0.5},
           {"free_mb": -1}, {"free_mb": 101}, {"load": "1"})
    return b"".join((
        b'\xff\xfe{"at": 1, "machine": "acme-bad"}\n', b"not json\n", b"[1, 2, 3]\n",
        (json.dumps({k: v for k, v in base.items() if k != "free_mb"}) + "\n").encode(),
        *(f"{head}{v}}}\n".encode() for v in ("NaN", "Infinity", "9" * 400)),
        *((json.dumps({**base, **o}) + "\n").encode() for o in bad)))


def _no_clock(*_a, **_kw):
    raise AssertionError("readings.hours must not read the clock")


# Each case: (name, steps, queries).
# steps: ("keep", at, said) | ("append", file, bytes) | ("dir", file) | ("locked", file, bytes) | ("files", names)
# queries: (name, until, count, home, [(start, processors, memory), ...])
CASES = [
    ("two_days_home_and_listed_with_gap_and_torn_line", [
        ("keep", M - 3000, {HERE: r(2.0, 4, 1000, 500), "acme-linux": r(8.0, 8, 2000, 1000)}),
        ("keep", M - 600, {HERE: r(6.0, 4, 1000, 300)}),
        ("keep", M + 120, {"acme-linux": r(0.0, 4, 1000, 1000)}),
        ("append", "2026-11-26.jsonl", b'{"at": 1795651300, "home": "acme-home", "cor'),
        ("keep", M + 2 * H + 30, {HERE: r(3.0, 2, 1000, 0), "acme-linux": r(3.0, 2, 1000, 200)}),
        ("keep", M + 2 * H + 900, {"acme-linux": r(1.0, 2, 1000, 600)}),
        ("files", ["2026-11-25.jsonl", "2026-11-26.jsonl"]),
    ], [
        ("acme-home", M + 3 * H, 4, True, [(M - H, 1.0, 0.6), (M, None, None),
                                           (M + H, None, None), (M + 2 * H, 1.5, 1.0)]),
        ("acme-linux", M + 3 * H, 4, False, [(M - H, 1.0, 0.5), (M, 0.0, 0.0),
                                             (M + H, None, None), (M + 2 * H, 1.0, 0.6)]),
    ]),
    ("same_name_home_and_listed_never_pooled", [
        ("keep", M + 10, {HERE: r(4.0, 4, 1000, 200), "acme-home": r(1.0, 4, 1000, 800)}),
        ("append", "2026-11-26.jsonl",
         raw(M + 20, {"home": "acme-home", "machine": "acme-home"}, 99.0, 1, 1000, 0)),
    ], [
        ("acme-home", M + H, 1, True, [(M, 1.0, 0.8)]),
        ("acme-home", M + H, 1, False, [(M, 0.25, 0.2)]),
    ]),
    ("hour_edges_start_in_end_out_to_one_ulp", [
        ("append", "2026-11-26.jsonl", b"".join(
            raw(at, "acme-edge", load, 1, 1000, 250) for at, load in (
                (math.nextafter(float(M), -math.inf), 99.0), (float(M), 1.0),
                (math.nextafter(float(M + H), -math.inf), 3.0), (float(M + H), 5.0),
                (math.nextafter(float(M + 2 * H), -math.inf), 7.0),
                (float(M + 2 * H), 99.0), (math.nextafter(float(M + 2 * H), math.inf), 99.0)))),
    ], [
        ("acme-edge", M + 2 * H, 2, False, [(M, 2.0, 0.75), (M + H, 6.0, 0.75)]),
    ]),
    ("running_mean_stays_finite", [
        ("append", "2026-11-26.jsonl", b"".join(
            raw(M + dt, "acme-big", load, 1, mem, free) for dt, load, mem, free in (
                (10, 1e308, 1e308, 0), (20, 1e308, 1e308, 0),
                (H + 10, 1e308, 1000, 1000), (H + 20, 0.0, 1000, 1000)))),
    ], [
        ("acme-big", M + 2 * H, 2, False, [(M, 1e308, 1.0), (M + H, 5e307, 0.0)]),
    ]),
    ("placed_by_at_with_no_calendar_date", [
        ("append", "1970-01-01.jsonl",
         raw(0, "acme-time", 2.0, 2, 100, 25) + raw(YEAR_9999, "acme-time", 4.0, 2, 100, 50)),
    ], [
        ("acme-time", -62135596800, 2, False,
         [(-62135596800 - 2 * H, None, None), (-62135596800 - H, None, None)]),
        ("acme-time", H, 2, False, [(-H, None, None), (0, 1.0, 0.75)]),
        ("acme-time", YEAR_9999 + 1, 2, False,
         [(YEAR_9999 + 1 - 2 * H, None, None), (YEAR_9999 + 1 - H, 2.0, 0.5)]),
    ]),
    ("skips_unusable_lines_non_day_and_unreadable", [
        ("append", "2026-11-26.jsonl", bad_lines() + raw(M + 10, "acme-bad", 2.0, 4, 100, 50)),
        ("append", "acme.jsonl", raw(M + 20, "acme-bad", 99.0, 1, 100, 0)),
        ("dir", "2026-11-25.jsonl"),
        ("locked", "2026-11-24.jsonl", raw(M + 20, "acme-bad", 99.0, 1, 100, 0)),
    ], [
        ("acme-bad", M + H, 1, False, [(M, 0.5, 0.5)]),
    ]),
    ("missing_folder_and_zero_count", [], [
        ("acme-none", M + H, 2, False, [(M - H, None, None), (M, None, None)]),
        ("acme-none", M, 0, True, []),
    ]),
]


class ReadingsByTheHour(unittest.TestCase):
    def run_case(self, steps, queries):
        with (tempfile.TemporaryDirectory(prefix="ak-readings-hours-") as tmp,
              patch.object(config, "HOME", Path(tmp)),
              patch.object(socket, "gethostname", return_value="acme-home")):
            (Path(tmp) / "state").mkdir()
            folder, locked = Path(tmp) / "state" / "readings", []
            try:
                for kind, *args in steps:
                    if kind == "keep":
                        readings.keep(*args)
                    elif kind == "files":
                        self.assertEqual(sorted(p.name for p in folder.iterdir()), args[0])
                    elif kind in ("append", "dir", "locked"):
                        folder.mkdir(exist_ok=True)
                        path = folder / args[0]
                        if kind == "append":
                            with path.open("ab") as file:
                                file.write(args[1])
                        elif kind == "dir":
                            path.mkdir()
                        elif os.geteuid() != 0:
                            path.write_bytes(args[1])
                            path.chmod(0)
                            locked.append(path)
                with (patch.object(readings.time, "time", _no_clock),
                      patch.object(readings.time, "monotonic", _no_clock),
                      patch.object(readings.time, "gmtime", _no_clock)):
                    for who, until, count, home, expected in queries:
                        got = readings.hours(who, until, count, home=home)
                        self.assertEqual([h.start for h in got], [e[0] for e in expected])
                        for h, (_, exp_p, exp_m) in zip(got, expected):
                            for val, exp in ((h.processors, exp_p), (h.memory, exp_m)):
                                if exp is None:
                                    self.assertIsNone(val)
                                else:
                                    self.assertTrue(val is not None and math.isfinite(val))
                                    self.assertAlmostEqual(val, exp)
            finally:
                for path in locked:
                    path.chmod(0o600)

    def test_readings_by_the_hour(self):
        for name, steps, queries in CASES:
            with self.subTest(name):
                self.run_case(steps, queries)


if __name__ == "__main__":
    unittest.main()
