"""Each machine check appends what each machine that answered said to a file of its UTC day.

state/machines.json keeps only each machine's last answer.  Each check also appends, to
state/readings/YYYY-MM-DD.jsonl, a newline and then a JSON line per machine that answered, each
ended by a newline: `at`, the check's time; `home`, the host's name, for this machine, or
`machine`, the name it was added under, for any other; then what it said as machines.json has
it, on Linux with the kernel's running totals of the microseconds some work stood waiting for a
processor, for memory and for the disk (`some … total=` of /proc/pressure).  The leading newline
ends bytes an interrupted write left; a day's file past five weeks goes at the next check, and a
file named otherwise stays.

Black-box: `AK_BIN` ticks in the box of `home.tick()` (tests/fixtures/akbin.py), its host named
acme-home and its /proc/pressure the test's; ssh is a fake answering the probe as a Linux
machine does for acme-linux and as a Mac does for acme-mac, and failing as ssh fails for
acme-gone.  The test reads the files itself.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, boxable

DAY = 86400
KEPT = 35 * DAY
HOME, LINUX, MAC, GONE = "acme-home", "acme-linux", "acme-mac", "acme-gone"
FOLDER = ".agentkit/state/readings"
STALLS = ("cpu_stall_us", "memory_stall_us", "io_stall_us")
SAID = "'processor arm64' 'cores 8' 'memory_mb 16384' 'free_mb 4096' 'load 1.5' " \
       "'disk_free_mb 204800' 'power 1'"
SSH = f"""#!/bin/sh
while [ "$#" -gt 0 ] && [ "$1" != -- ]; do shift; done
case $2:$3 in
  {LINUX}:"bash -c "*) printf '%s\\n' 'system Linux' {SAID} 'battery 0' \\
    'cpu_stall_us 7' 'memory_stall_us 8' 'io_stall_us 9' ;;
  {MAC}:"bash -c "*) printf '%s\\n' 'system macOS' {SAID} 'battery 1' ;;
  *) exit 255 ;;
esac
"""


def day(at):
    return time.strftime("%Y-%m-%d.jsonl", time.gmtime(at))


@unittest.skipUnless(boxable() and Path("/proc/pressure").is_dir(),
                     "no bwrap able to box a tick, or no /proc/pressure to bind over, here")
class MachineReadingsAreKept(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        config = home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() +
                          "".join(f"\n[machines.{name}]\n" for name in (LINUX, MAC, GONE)))
        home.fake("ssh", SSH)
        self.pressure = home.root / "pressure"
        self.pressure.mkdir()

    def check(self, n):
        """The `n`th check, this host's kernel saying totals of its own: its time, and each line
        it should have written, as a list of its keys and values in order."""
        for i, stall in enumerate(("cpu", "memory", "io")):
            (self.pressure / stall).write_text(
                f"some avg10=1.00 avg60=0.50 avg300=0.25 total={1000 * n + i}\n"
                "full avg10=0.00 avg60=0.00 avg300=0.00 total=5\n")
        done = self.home.tick(box=("--unshare-uts", "--hostname", HOME,
                                   "--ro-bind", str(self.pressure), "/proc/pressure"))
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/machines.json").read_text())
        self.assertFalse(record[GONE]["checks"][-1][1], "the machine away answered")
        said = {("home", HOME): record["this one"]["said"],
                ("machine", LINUX): record[LINUX]["said"], ("machine", MAC): record[MAC]["said"]}
        [at] = {one["at"] for one in said.values()}
        self.assertEqual([said["home", HOME].get(stall) for stall in STALLS],
                         [1000 * n + i for i in range(len(STALLS))])
        self.assertEqual([said["machine", LINUX].get(stall) for stall in STALLS], [7, 8, 9])
        self.assertFalse(set(STALLS) & set(said["machine", MAC]))
        return at, [[["at", at], [key, name],
                     *([reading, value] for reading, value in one.items() if reading != "at")]
                    for (key, name), one in said.items()]

    def test_each_check_appends_a_line_per_machine_that_answered(self):
        at, first = self.check(1)
        folder = self.home.path / FOLDER
        [written] = folder.iterdir()
        self.assertEqual(written.name, day(at))
        pieces = written.read_bytes().split(b"\n")
        self.assertEqual((pieces[0], len(pieces), pieces[-1]), (b"", 5, b""))
        self.assertCountEqual([list(map(list, json.loads(line).items())) for line in pieces[1:-1]],
                              first)

        # an interrupted write's bytes at the end of each day's file the next check may write
        torn = b'{"at": 1, "machine": "acme-torn", "cor'
        for name in (day(at), day(at + DAY)):
            with (folder / name).open("ab") as file:
                file.write(torn)
        old, young = day(at - KEPT - 2 * DAY), day(at - KEPT + 2 * DAY)
        (folder / old).write_text('{"at": 1, "machine": "acme-linux"}\n')
        others = {name: f"{name}\n".encode() for name in (
            young, f"{old}.bak", old.removesuffix(".jsonl"), "acme.jsonl")}
        for name, data in others.items():
            (folder / name).write_bytes(data)
        then, second = self.check(2)
        latest = day(then)

        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         sorted({day(at), day(at + DAY), latest, *others}))
        self.assertEqual({name: (folder / name).read_bytes() for name in others}, others)
        self.assertIn(torn + b"\n", (folder / latest).read_bytes())
        kept, left = [], []
        for name in {day(at), latest}:
            for piece in (folder / name).read_bytes().split(b"\n"):
                if piece and piece != torn:
                    try:
                        line = json.loads(piece)
                    except ValueError:
                        left.append(piece)
                    else:
                        self.assertEqual(name, day(line["at"]))
                        kept.append(list(map(list, line.items())))
        self.assertEqual(left, [])
        self.assertCountEqual(kept, first + second)


if __name__ == "__main__":
    unittest.main()
