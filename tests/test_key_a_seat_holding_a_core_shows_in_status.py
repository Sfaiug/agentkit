"""`ak run status` names, under the host's lines, each seat the tick's last reading found holding
a whole core (tests/test_key_a_seat_holding_a_core_is_told.py), and how long it had held it then,
longest first: `seats holding a core: fix-api 6m · parser 3m`, in a seat's own status too.  While
none is, as on a host where none ever was, there is no such line.

Black-box: the program `AK_BIN` names ticks (`home.tick()`) on a stand-in cgroup tree
(AK_CGROUP_ROOT, AK_CGROUP_FILE) whose CPU counters the test moves, and a clock it steps
(AK_CORES_CLOCK).  No wait is real.
"""

import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SOCKET, Home, boxable

SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
FIX, PARSER = "agentkit-seat-fix-api-89abcdef.scope", "agentkit-seat-parser-0123abcd.scope"
START = 1_800_000_000
# Each tick's clock past START, and the CPU seconds each seat's scope has used by then: fix-api
# holds a core from the first interval, parser from the second, and neither in the last.
TICKS = [(0, {FIX: 0, PARSER: 0}), (180, {FIX: 180, PARSER: 0}), (360, {FIX: 360, PARSER: 180}),
         (540, {FIX: 360, PARSER: 180})]


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ASeatHoldingACoreShowsInStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        # a collection on record from just now: one due would outlive the tick
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        root, membership, clock = (home.root / name for name in ("cgroup", "membership", "clock"))
        seats = root / SERVICE / "agentkit.slice" / f"{SOCKET}.slice" / f"{SOCKET}.slice"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership),
                        AK_CORES_CLOCK=str(clock))
        cls.before = cls.held()
        cls.after = []
        for at, used in TICKS:
            clock.write_text(str(START + at))
            for scope, seconds in used.items():
                (seats / scope).mkdir(parents=True, exist_ok=True)
                (seats / scope / "cpu.stat").write_text(
                    f"usage_usec {seconds * 1_000_000}\nuser_usec 0\nsystem_usec 0\n")
            done = home.tick()
            assert done.code == 0, done.out + done.err
            cls.after.append(cls.held())

    @classmethod
    def held(cls):
        """The lines of `ak run status`, in a seat holding none, naming the seats holding a core."""
        done = cls.home.ak("run", "status", env={"AGENTKIT_SESSION": "acme"})
        assert done.code == 0 and "seat acme's runs only" in done.out, done.out + done.err
        return [line for line in done.out.splitlines() if line.startswith("seats holding a core")]

    def test_a_seat_over_a_core_shows_with_how_long(self):
        self.assertEqual(self.after[1], ["seats holding a core: fix-api 3m"])

    def test_seats_holding_a_core_show_on_one_line_longest_first(self):
        self.assertEqual(self.after[2], ["seats holding a core: fix-api 6m · parser 3m"])

    def test_no_line_on_a_host_where_no_seat_ever_held_a_core(self):
        self.assertEqual([self.before, self.after[0]], [[], []])

    def test_no_line_after_a_tick_in_which_no_seat_held_a_core(self):
        self.assertEqual(self.after[3], [])

    def test_a_seat_holding_a_core_in_two_scopes_shows_once_with_the_longest(self):
        # a respawn's new scope beside its old one
        with Home() as home:
            home.write(".agentkit/state/watch.json", {"seat_cores": {
                FIX: {"at": 540, "since": 0},
                "agentkit-seat-fix-api-0123abcd.scope": {"at": 540, "since": 180}}})
            done = home.ak("run", "status")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual([line for line in done.out.splitlines()
                          if line.startswith("seats holding a core")],
                         ["seats holding a core: fix-api 9m"])


if __name__ == "__main__":
    unittest.main()
