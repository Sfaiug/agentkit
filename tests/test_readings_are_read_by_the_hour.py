"""What the machine-page key cannot reach of `readings.hours`: `home` lines apart from a listed
machine's of the same name, memory means, unusable lines and non-regular/unreadable files, exact
hour edges, finite running means and calendar-free placement with no clock read."""

import calendar, json, math, os, socket, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, machines, readings  # noqa: E402

H, M, Y9999 = 3600, calendar.timegm((2026, 11, 26, 0, 0, 0, 0, 0, 0)), 253402300799


def raw(at, who, load=1.0, cores=2, memory_mb=100, free_mb=50, stall=...):
    tag = {"machine": who} if isinstance(who, str) else who
    row = {"at": at, **tag, "load": load, "cores": cores, "memory_mb": memory_mb, "free_mb": free_mb}
    if stall is not ...:
        row["memory_stall_us"] = stall
    return (json.dumps(row) + "\n").encode()


def _no_clock(*_a, **_kw):
    raise AssertionError("readings.hours must not read the clock")


class ReadingsByTheHour(unittest.TestCase):
    def check(self, query, expected):
        with (patch.object(readings.time, "time", _no_clock), patch.object(readings.time, "monotonic", _no_clock),
              patch.object(readings.time, "gmtime", _no_clock)):
            got = readings.hours(*query[:-1], home=query[-1])
        self.assertEqual([h.start for h in got], [e[0] for e in expected])
        for h, row in zip(got, expected):
            _, ep, em = row[:3]
            ew = row[3] if len(row) > 3 else None
            es = row[4] if len(row) > 4 else (("processors",) if ep is not None and ep > 1 else ())
            for val, exp in ((h.processors, ep), (h.memory, em), (h.memory_wait, ew)):
                self.assertIsNone(val) if exp is None else self.assertAlmostEqual(val, exp)
            self.assertEqual(h.short_of, es)

    def test_home_unusable_and_bounds(self):
        base = {"at": M + 10, "machine": "acme-bad", "load": 1, "cores": 2, "memory_mb": 100, "free_mb": 50}
        head = f'{{"at": {M + 10}, "machine": "acme-bad", "cores": 2, "memory_mb": 100, "free_mb": 50, "load": '
        bad = ({"at": True}, {"load": False}, {"cores": True}, {"memory_mb": True}, {"free_mb": False},
               {"at": -1}, {"load": -0.1}, {"cores": 0.5}, {"memory_mb": 0.5}, {"free_mb": -1}, {"free_mb": 101}, {"load": "1"})
        unusable = b"".join((b'\xff\xfe{"at": 1, "machine": "acme-bad"}\n', b"not json\n", b"[1, 2, 3]\n",
                             (json.dumps({k: v for k, v in base.items() if k != "free_mb"}) + "\n").encode(),
                             *(f"{head}{v}}}\n".encode() for v in ("NaN", "Infinity", "9" * 400)),
                             *((json.dumps({**base, **o}) + "\n").encode() for o in bad)))
        with (tempfile.TemporaryDirectory(prefix="ak-readings-hours-") as tmp,
              patch.object(config, "HOME", Path(tmp)), patch.object(socket, "gethostname", return_value="acme-home")):
            folder, locked = Path(tmp) / "state/readings", Path(tmp) / "state/readings/2026-11-24.jsonl"
            folder.parent.mkdir()
            self.check(("acme-none", M + H, 1, False), [(M, None, None)])
            self.check(("acme-none", M, 0, True), [])
            said = {"system": "Linux", "processor": "x86_64", "cores": 4, "memory_mb": 1000, "disk_free_mb": 50000, "battery": 0, "power": 1}
            for at, group in ((M - 3000, {machines.HERE: {**said, "load": 2.0, "free_mb": 500}}),
                              (M - 600, {machines.HERE: {**said, "load": 6.0, "free_mb": 300}}),
                              (M + 10, {machines.HERE: {**said, "load": 4.0, "free_mb": 200}, "acme-home": {**said, "load": 1.0, "free_mb": 800}})):
                readings.keep(at, group)
            try:
                with (folder / "2026-11-26.jsonl").open("ab") as file:
                    file.write(b"".join((
                        raw(M + 20, {"home": "acme-home", "machine": "acme-home"}, 99.0, 1, 1000, 0),
                        unusable, raw(M + 10, "acme-bad", 2.0, 4),
                        *(raw(at, "acme-edge", load, 1, 1000, 250) for at, load in (
                            (math.nextafter(float(M), -math.inf), 99.0), (float(M), 1.0), (math.nextafter(float(M + H), -math.inf), 3.0),
                            (float(M + H), 5.0), (math.nextafter(float(M + 2 * H), -math.inf), 7.0), (float(M + 2 * H), 99.0))),
                        *(raw(M + dt, "acme-big", load, 1, mem, free) for dt, load, mem, free in (
                            (10, 1e308, 1e308, 0), (20, 1e308, 1e308, 0), (H + 10, 1e308, 1000, 1000), (H + 20, 0.0, 1000, 1000))),
                        raw(0, "acme-time", 2.0, 2, 100, 25), raw(Y9999, "acme-time", 4.0, 2))))
                (folder / "acme.jsonl").write_bytes(raw(M + 20, "acme-bad", 99.0, 1))
                (folder / "2026-11-22.jsonl").mkdir()
                os.mkfifo(folder / "2026-11-23.jsonl")
                if os.geteuid() != 0:
                    locked.write_bytes(raw(M + 20, "acme-bad", 99.0, 1))
                    locked.chmod(0)
                descriptors = len(os.listdir("/dev/fd"))
                for q, exp in (
                    (("acme-home", M + H, 2, True), [(M - H, 1.0, 0.6), (M, 1.0, 0.8)]), (("acme-home", M + H, 1, False), [(M, 0.25, 0.2)]),
                    (("acme-bad", M + H, 1, False), [(M, 0.5, 0.5)]), (("acme-edge", M + 2 * H, 2, False), [(M, 2.0, 0.75), (M + H, 6.0, 0.75)]),
                    (("acme-edge", M + 2 * H - 0.5, 1, False), [(M + H - 0.5, 4.0, 0.75)]),
                    (("acme-big", M + 2 * H, 2, False), [(M, 1e308, 1.0), (M + H, 5e307, 0.0)]),
                    (("acme-time", -62135596800, 1, False), [(-62135596800 - H, None, None)]),
                    (("acme-time", H, 2, False), [(-H, None, None), (0, 1.0, 0.75)]), (("acme-time", Y9999 + 1, 1, False), [(Y9999 + 1 - H, 2.0, 0.5)]),
                ):
                    self.check(q, exp)
                self.assertEqual(len(os.listdir("/dev/fd")), descriptors)     # the directory's closed too
            finally:
                if locked.exists():
                    locked.chmod(0o600)

    def test_memory_wait_and_shortages(self):
        tenth = 360_000_000
        huge_at = 10 ** 303
        with (tempfile.TemporaryDirectory(prefix="ak-readings-wait-") as tmp,
              patch.object(config, "HOME", Path(tmp)), patch.object(socket, "gethostname", return_value="acme-home")):
            folder = Path(tmp) / "state/readings"
            folder.mkdir(parents=True)
            lines = [
                # Exact boundary: 1.0 processors is not short (even across loads whose running
                # mean drifts above 1), a mean just above 1 that rounds to 1.0 in float still is,
                # 359_999_999 us (< tenth) is not short; out-of-order lines sort by `at`.
                raw(M + 1200, "acme-edge", 2.0, 2, stall=tenth - 1),
                raw(M + 600, "acme-edge", 2.0, 2, stall=0),
                *(raw(M + 600 * i, "acme-exact", load, 4) for i, load in enumerate((4.25, 8.5, 0.25, 2.25, 6.25, 2.5))),
                *(raw(M + 300 * i, "acme-dec-exact", load, 4) for i, load in enumerate((3.6, 4.4))),
                *(raw(M + 300 * i, "acme-just-over", load, cores) for i, (cores, load) in enumerate((
                    (188, 188.01), (189, 188.94), (190, 190.15), (191, 190.80),
                    (192, 192.15), (193, 192.94), (194, 194.01)))),
                # Next hour: cross-hour rise counts for the later hour; exact tenth + load > cores -> both.
                raw(M + H + 600, "acme-edge", 4.0, 2, stall=2 * tenth - 1),
                # Invalid or absent counter carries none (keeps load/memory) and never bridges a step.
                raw(M + 10, "acme-gap", 2.0, 2, stall=0),
                *(raw(M + 100 + i, "acme-gap", 2.0, 2, stall=bad)
                  for i, bad in enumerate((-1, True, False, 1.5, 1.0, "100", None))),
                f'{{"at": {M + 200}, "machine": "acme-gap", "load": 2.0, "cores": 2, "memory_mb": 100, "free_mb": 50, "memory_stall_us": 1e-9999999999999999999}}\n'.encode(),
                raw(M + 500, "acme-gap", 2.0, 2, stall=tenth),
                # Float timestamps round-trip as float on hour edges and clamped intervals.
                *(raw(at, "acme-float-at", 1.0, 1, stall=stall) for at, stall in (
                    (float(M), 0), (M + 120.2, 500_000_000), (M + 500.1, 0), (1795651939.8999999, 500_000_000))),
                raw(M + 0.2, "acme-float-edge", 1.0, 1),
                raw(M + H + 0.2, "acme-float-edge", 2.0, 1),
                raw(M + 2 * H + 0.2, "acme-float-edge", 3.0, 1),
                raw(M - 350, "acme-edge-gap", 1.0, 4, stall=0),
                raw(M - 100, "acme-edge-gap", 1.0, 4),
                raw(M + 10, "acme-edge-gap", 1.0, 4, stall=tenth),
                # Restart (counter lower than before) gives 0 wait; subsequent rise still counts.
                raw(M + 100, "acme-restart", 1.0, 2, stall=900_000_000),
                raw(M + 700, "acme-restart", 1.0, 2, stall=100_000_000),
                raw(M + H + 100, "acme-restart", 1.0, 2, stall=100_000_000 + tenth),
                # Clamping: rise past dt (even 10**400) caps at dt; same timestamp caps at 0;
                # cross-hour rise past an hour caps memory_wait at 1.0; huge integer `at` stays finite.
                raw(M + 100, "acme-clamp", 1.0, 2, stall=0),
                raw(M + 160, "acme-clamp", 1.0, 2, stall=10 ** 400),
                raw(M + 160, "acme-clamp", 1.0, 2, stall=10 ** 400 + tenth),
                raw(M + 100, "acme-cap", 1.0, 4, stall=0),
                raw(M + H + 1900, "acme-cap", 1.0, 4, stall=4_500_000_000),
                raw(0, "acme-huge-at", 1.0, 4, stall=0),
                raw(huge_at, "acme-huge-at", 1.0, 4, stall=tenth),
                # Many small steps summing to an exact tenth avoid float drift.
                *(raw(M + i * 50, "acme-steps", 1.0, 2, stall=i * 6_000_000) for i in range(61)),
                # Single counter reading with no prior reading gives no wait; home stays apart from machine.
                raw(M + 100, "acme-one", 1.0, 2, stall=tenth),
                raw(M + 100, {"home": "acme-home"}, 1.0, 2, stall=0),
                raw(M + 700, {"home": "acme-home"}, 1.0, 2, stall=tenth),
                raw(M + 100, "acme-home", 1.0, 2),
            ]
            (folder / "2026-11-26.jsonl").write_bytes(b"".join(lines))
            for q, exp in (
                (("acme-edge", M + 2 * H, 2, False), [
                    (M, 1.0, 0.5, (tenth - 1) / 3_600_000_000, ()),
                    (M + H, 2.0, 0.5, 0.1, ("processors", "memory")),
                ]),
                (("acme-exact", M + H, 1, False), [(M, 1.0, 0.5, None, ())]),
                (("acme-dec-exact", M + H, 1, False), [(M, 1.0, 0.5, None, ())]),
                (("acme-just-over", M + H, 1, False), [(M, 1.0, 0.5, None, ("processors",))]),
                # Window starting at M + H still picks up the step from the reading before M + H.
                (("acme-edge", M + 2 * H, 1, False), [(M + H, 2.0, 0.5, 0.1, ("processors", "memory"))]),
                (("acme-gap", M + H, 1, False), [(M, 1.0, 0.5, None, ())]),
                (("acme-float-at", M + H, 1, False), [(M, 1.0, 0.5, 0.1, ("memory",))]),
                (("acme-float-edge", M + 2 * H + 0.2, 2, False), [(M + 0.2, 1.0, 0.5, None, ()), (M + H + 0.2, 2.0, 0.5, None, ("processors",))]),
                (("acme-edge-gap", M + H, 1, False), [(M, 0.25, 0.5, None, ())]),
                (("acme-restart", M + 3 * H, 3, False), [
                    (M, 0.5, 0.5, 0.0, ()),
                    (M + H, 0.5, 0.5, 0.1, ("memory",)),
                    (M + 2 * H, None, None, None, ()),
                ]),
                (("acme-clamp", M + H, 1, False), [(M, 0.5, 0.5, 60 / H, ())]),
                (("acme-cap", M + 2 * H, 2, False), [(M, 0.25, 0.5, None, ()), (M + H, 0.25, 0.5, 1.0, ("memory",))]),
                (("acme-huge-at", huge_at + 1, 1, False), [(huge_at + 1 - H, 0.25, 0.5, 0.1, ("memory",))]),
                (("acme-steps", M + H, 1, False), [(M, 0.5, 0.5, 0.1, ("memory",))]),
                (("acme-one", M + H, 1, False), [(M, 0.5, 0.5, None, ())]),
                (("acme-home", M + H, 1, True), [(M, 0.5, 0.5, 0.1, ("memory",))]),
                (("acme-home", M + H, 1, False), [(M, 0.5, 0.5, None, ())]),
            ):
                self.check(q, exp)


if __name__ == "__main__":
    unittest.main()
