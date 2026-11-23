"""`ak` on a home whose slice's freezer reads `1`, as a paused firing leaves it, prints one line
and exits 1 before anything that may wait on what is frozen: the config's and the state's locks a
frozen process may hold, the seats' tmux server.  The line says that ak stands still on this
machine, for how long it has had no proof that it is ak's home, or that it has none, and that it
carries on by itself once it holds its lease on ak's remote again.  So does the menu a client
opens there, `ak --client`, and a dry run of either.  A home whose freezer reads `0`, or a `1`
that is not its whole reading, is not there, or is a pipe nobody writes to, opens the menu as
today, its proof however old: only the freezer says ak stands still.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, built
with their home, its record and its clock as tests/test_key_home_freezes_without_its_lease.py
builds them; each case builds its own.  What came back is `ak`'s exit and whether a line of its
output is the line: no other output is compared.
"""

import fcntl
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from test_key_home_freezes_without_its_lease import SLICE, Firings, now

LINE = ("ak stands still on this machine: {} that it is ak's home. It carries on by itself once "
        "it holds its lease on ak's remote again.")
CONFIG = Path(".agentkit/config.toml")
STATE_LOCK = Path(".agentkit/state/watch.lock")     # the one the menu's start takes


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class TheMenuSaysAkStandsStill(Firings, unittest.TestCase):
    def says(self, machine, at, since, *args):
        """`ak` with `args` on `machine` at AK_NOW `at` exits 1, one line of its output the line
        whose `since` says how long it has had no proof."""
        done = machine.ak(*args, env={"AK_NOW": at})
        self.assertEqual(done.code, 1, done)
        self.assertIn(LINE.format(since), done.out.splitlines(), done)

    def test_a_home_paused_with_a_proof_12_minutes_old_says_so_and_so_does_its_clients_menu(self):
        machines = self.machines()
        home, = machines
        self.home(home)
        machines.break_remote("unreachable")
        self.paused(home, now(12))
        for args in ((), ("--client",), ("--dry-run",), ("--client", "--dry-run")):
            with self.subTest(args=args):
                self.says(home, now(12), "for 12m it has had no proof", *args)

    def test_a_home_paused_with_no_proof_says_it_has_none(self):
        machines = self.machines()
        home, = machines
        self.record(home, "yes")
        machines.break_remote("unreachable")
        self.paused(home, now(0))
        self.says(home, now(0), "it has no proof")

    def test_the_config_and_state_locks_held_elsewhere_hold_no_line_back(self):
        machines = self.machines()
        home, = machines
        self.record(home, "yes")
        machines.break_remote("unreachable")
        self.paused(home, now(0))
        # an old name, which the first command renames under the config's lock
        home.write(CONFIG, "rounds = 2\n" + (home.path / CONFIG).read_text())
        # the config's lock is its directory's
        for lock in (os.open(home.path / CONFIG.parent, os.O_RDONLY),
                     os.open(home.path / STATE_LOCK, os.O_RDONLY | os.O_CREAT)):
            self.addCleanup(os.close, lock)
            fcntl.flock(lock, fcntl.LOCK_EX)
        self.says(home, now(0), "it has no proof")

    def test_a_home_not_paused_or_with_no_freezer_opens_the_menu_its_proof_however_old(self):
        # and a `1` that is not the whole reading, past the first 16 bytes: a firing reads it whole
        for freezer in (b"0", b"1" + b" " * 16 + b"0", None, "a pipe"):
            with self.subTest(freezer=freezer):
                home, = self.machines(freezer=None if freezer == "a pipe" else freezer)
                self.home(home)
                if freezer == "a pipe":     # past the firings: a read of it waits for a writer
                    (home.root / "cgroups" / SLICE).mkdir(parents=True)
                    os.mkfifo(home.root / "cgroups" / SLICE / "cgroup.freeze")
                done = home.ak("--dry-run", env={"AK_NOW": now(12)})
                self.assertEqual(done.code, 0, done)
                self.assertNotIn("ak stands still on this machine:", done.out + done.err)


if __name__ == "__main__":
    unittest.main()
