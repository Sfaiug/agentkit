"""Each tick sets the runs slice's MemoryHigh to ak's slice's ceiling less what the seats hold
and a margin, never under one run's cap, and sets nothing where no ceiling is set.

At the slice's MemoryMax every allocation in it reclaims first, so a seat waited 29 s to draw a
scroll behind the runs' memory (27 Oct 2026).  The seats are what the slice holds outside the
runs; the margin covers what they grew by since the last tick.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py.  The tick reads a fake cgroup tree
(AK_CGROUP_ROOT, AK_CGROUP_FILE) and the ceiling from a drop-in in the Home, and its systemctl
records each argv and succeeds.
"""

import os
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, SOCKET, boxable, Home

GB = 1024
SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"


class Slice:
    """ak's slice in a fake cgroup tree, its runs holding 3 G."""

    def __init__(self, home, ceiling):
        root = home.root / "cgroup"
        self.dir = root / SERVICE / "agentkit.slice" / f"{SOCKET}.slice"
        runs = self.dir / f"{SOCKET}-runs.slice"
        runs.mkdir(parents=True)
        (runs / "memory.current").write_text(str(3 * GB * 1024 ** 2))
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership))
        if ceiling:
            home.write(f".config/systemd/user/{SOCKET}.slice.d/50-memory.conf",
                       f"[Slice]\nMemoryMax={ceiling}\n")
        config = home.path / ".agentkit" / "config.toml"     # no audit seat to open
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        home.fake("systemctl", LOG.format(python=shlex.quote(sys.executable),
                                          log=shlex.quote(str(home.log("systemctl")))))

    def seats(self, mb):
        """The seats hold `mb`: the slice holds that beside its runs."""
        (self.dir / "memory.current").write_text(str((mb + 3 * GB) * 1024 ** 2))


def highs(home):
    """Each MemoryHigh the ticks set on the runs slice, in MiB, oldest first."""
    return [int(argv[-1].removeprefix("MemoryHigh=").removesuffix("M"))
            for argv in home.calls("systemctl")
            if argv[:4] == ["--user", "set-property", "--runtime", f"{SOCKET}-runs.slice"]]


def ticked(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err
    return highs(home)[-1]


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class RunsGiveWayToSeats(unittest.TestCase):
    def test_runs_get_the_ceiling_less_the_seats_and_a_margin_that_covers_their_growth(self):
        with Home() as home:
            slice_ = Slice(home, "10G")
            slice_.seats(4 * GB)
            first = ticked(home)
            self.assertLess(first, 6 * GB)
            self.assertGreater(first, 5 * GB)
            slice_.seats(5 * GB)
            self.assertLessEqual(ticked(home), first - GB)

    def test_runs_keep_one_runs_cap_however_much_the_seats_hold(self):
        with Home() as home:
            config = home.path / ".agentkit" / "config.toml"
            config.write_text("run_memory_max_mb = 3072\n" + config.read_text())
            Slice(home, "10G").seats(9 * GB)
            self.assertEqual(ticked(home), 3072)

    def test_no_ceiling_sets_no_memory_high(self):
        with Home() as home:
            Slice(home, None).seats(4 * GB)
            done = home.tick()
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(highs(home), [])


if __name__ == "__main__":
    unittest.main()
