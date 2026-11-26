"""What the machine-page key cannot reach of `readings.hours`: this host's `home` lines apart from
a listed machine's of the same name, unusable lines and unreadable files, exact edges, finite
running means and calendar-free placement with no clock read."""

import calendar, json, math, os, socket, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, machines, readings  # noqa: E402

H, M, Y9999 = 3600, calendar.timegm((2026, 11, 26, 0, 0, 0, 0, 0, 0)), 253402300799


def raw(at, who, load=1.0, cores=2, memory_mb=100, free_mb=50):
    tag = {"machine": who} if isinstance(who, str) else who
    return (json.dumps({"at": at, **tag, "load": load, "cores": cores, "memory_mb": memory_mb, "free_mb": free_mb}) + "\n").encode()


def _no_clock(*_a, **_kw):
    raise AssertionError("readings.hours must not read the clock")


class ReadingsByTheHour(unittest.TestCase):
    def check(self, query, expected):
        with (patch.object(readings.time, "time", _no_clock), patch.object(readings.time, "monotonic", _no_clock),
              patch.object(readings.time, "gmtime", _no_clock)):
            got = readings.hours(*query[:-1], home=query[-1])
        self.assertEqual([h.start for h in got], [e[0] for e in expected])
        for h, (_, ep, em) in zip(got, expected):
            for val, exp in ((h.processors, ep), (h.memory, em)):
                self.assertIsNone(val) if exp is None else self.assertAlmostEqual(val, exp)

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
            readings.keep(M + 10, {machines.HERE: {**said, "load": 4.0, "free_mb": 200}, "acme-home": {**said, "load": 1.0, "free_mb": 800}})
            try:
                with (folder / "2026-11-26.jsonl").open("ab") as file:
                    file.write(b"".join((
                        raw(M + 20, {"home": "acme-home", "machine": "acme-home"}, 99.0, 1, 1000, 0),
                        unusable, raw(M + 10, "acme-bad", 2.0, 4),
                        raw(math.nextafter(float(M), -math.inf), "acme-edge", 99.0, 1), raw(float(M), "acme-edge", 1.0, 1),
                        raw(math.nextafter(float(M + H), -math.inf), "acme-edge", 3.0, 1), raw(float(M + H), "acme-edge", 99.0, 1),
                        raw(M + 10, "acme-big", 1e308, 1, 1e308, 0), raw(M + 20, "acme-big", 1e308, 1, 1e308, 0), raw(Y9999, "acme-time", 4.0, 2))))
                (folder / "acme.jsonl").write_bytes(raw(M + 20, "acme-bad", 99.0, 1))
                (folder / "2026-11-25.jsonl").mkdir()
                if os.geteuid() != 0:
                    locked.write_bytes(raw(M + 20, "acme-bad", 99.0, 1))
                    locked.chmod(0)
                for q, exp in ((("acme-home", M + H, 1, True), [(M, 1.0, 0.8)]), (("acme-home", M + H, 1, False), [(M, 0.25, 0.2)]),
                               (("acme-bad", M + H, 1, False), [(M, 0.5, 0.5)]), (("acme-edge", M + H, 1, False), [(M, 2.0, 0.5)]),
                               (("acme-big", M + H, 1, False), [(M, 1e308, 1.0)]), (("acme-time", -62135596800, 1, False), [(-62135596800 - H, None, None)]),
                               (("acme-time", Y9999 + 1, 1, False), [(Y9999 + 1 - H, 2.0, 0.5)])):
                    self.check(q, exp)
            finally:
                if locked.exists():
                    locked.chmod(0o600)


if __name__ == "__main__":
    unittest.main()
