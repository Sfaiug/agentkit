"""The seats a client is in and the unit holding the tmux server go first among seats.

Black-box: the program `AK_BIN` names, real clients on a Home's private tmux server, a fake
cgroup tree (AK_CGROUP_ROOT, AK_CGROUP_FILE), and a systemctl that records each argv and writes
the weight into that tree, as systemd would.
"""

import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, LOG, REAL_TMUX, SOCKET, Home, boxable
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
ACME, TWO = "agentkit-seat-acme-89abcdef.scope", "agentkit-seat-acme-two-4567cdef.scope"
DECOY = "agentkit-seat-acme-0123abcd.scope"
# systemd's way: only a set-property is answered, and the unit's directory takes the weight,
# whole, as the kernel's file reads: a reader polling it never finds it empty mid-write.
WRITES = """for a do :; done
case $a in CPUWeight=*)
  find "$AK_CGROUP_ROOT" -type d -name "$4" | while read -r d; do
    echo "${a#*=}" >"$d/.weight.$$" && mv "$d/.weight.$$" "$d/cpu.weight"
  done
esac
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheSeatYouAreIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        root = home.root / "cgroup"
        owner = root / SERVICE
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership))
        cls.seats = owner / "agentkit.slice" / f"{SOCKET}.slice" / f"{SOCKET}.slice"
        # The account's own seats' slice, in the same tree, while the Home's server is another.
        cls.decoy = owner / "agentkit.slice" / "agentkit-seats.slice" / DECOY
        cls.decoy.mkdir(parents=True)
        (cls.decoy / "cpu.weight").write_text("100\n")
        cls.watch_systemctl()
        Seat(home, "acme")
        Seat(home, "acme-two")
        # Seats open with no conf: the first tick gives a server already up its hooks.
        if boxable():
            done = home.tick()
            assert done.code == 0, done.err

    @classmethod
    def watch_systemctl(cls):
        cls.home.fake("systemctl", LOG.format(python=shlex.quote(sys.executable),
                                              log=shlex.quote(str(cls.home.log("systemctl"))))
                      + WRITES)

    def setUp(self):
        if not boxable():
            self.skipTest("no bubblewrap for the tick that gives the server its hooks")
        self.attached = False
        self.addCleanup(self.leave)
        for unit in (ACME, TWO):
            self.set_weight(unit, 100)

    def scope(self, unit):
        path = self.seats / unit
        path.mkdir(parents=True, exist_ok=True)
        return path

    def set_weight(self, unit, weight):
        (self.scope(unit) / "cpu.weight").write_text(f"{weight}\n")

    def weight(self, unit):
        try:
            return int((self.scope(unit) / "cpu.weight").read_text())
        except FileNotFoundError:
            return None

    def wait_weights(self, acme, two, bound=30):
        deadline = time.monotonic() + bound
        while (self.weight(ACME), self.weight(TWO)) != (acme, two):
            if time.monotonic() > deadline:
                self.fail(f"weights read {self.weight(ACME), self.weight(TWO)}, not {acme, two}")
            time.sleep(0.05)

    def asked(self):
        return [call for call in self.home.calls("systemctl") if "set-property" in call]

    def attach(self, seat):
        """A person's client, by tmux alone: nothing of ak's runs but the server's hooks."""
        Terminal(self.home, "-L", SOCKET, "attach-session", "-t", f"={seat}:", program=REAL_TMUX)
        self.attached = True
        deadline = time.monotonic() + 30
        while f"{seat}\n" != self.home.tmux("list-clients", "-F", "#{session_name}").out:
            self.assertLess(time.monotonic(), deadline, "the client never attached")
            time.sleep(0.05)

    def leave(self):
        """No client left, and the hooks' passes have said so."""
        if self.attached:
            for seat in ("acme", "acme-two"):
                self.home.tmux("detach-client", "-s", f"={seat}:")
            self.wait_weights(100, 100)

    def test_a_client_attaching_and_detaching_moves_its_seat_alone(self):
        before = len(self.asked())
        self.attach("acme")
        self.wait_weights(10000, 100)
        self.assertNotIn(TWO, [call[3] for call in self.asked()[before:]])
        self.home.tmux("detach-client", "-s", "=acme:")
        self.wait_weights(100, 100)

    def test_a_client_moving_between_seats_takes_the_weight_with_it(self):
        self.attach("acme")
        self.wait_weights(10000, 100)
        tty = self.home.tmux("list-clients", "-F", "#{client_tty}").out.strip()
        done = self.home.tmux("switch-client", "-c", tty, "-t", "=acme-two:")
        self.assertEqual(done.code, 0, done.err)
        self.wait_weights(100, 10000)

    def test_a_renamed_seat_keeps_its_place_on_the_scope_it_launched_in(self):
        unit = "agentkit-seat-acme-three-0a1b2c3d.scope"
        self.set_weight(unit, 100)
        self.addCleanup(shutil.rmtree, self.scope(unit))
        Seat(self.home, "acme-three")
        self.addCleanup(self.home.tmux, "kill-session", "-t", "=lagoon:")
        self.attach("acme-three")
        self.assertEqual(self.home.ak("orch", "front").code, 0)
        self.assertEqual(self.weight(unit), 10000)
        done = self.home.ak("orch", "rename", "acme-three", "lagoon")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.home.ak("orch", "front").code, 0)
        self.assertEqual(self.weight(unit), 10000)
        self.home.tmux("detach-client", "-s", "=lagoon:")
        self.assertEqual(self.home.ak("orch", "front").code, 0)
        self.assertEqual(self.weight(unit), 100)

    def test_the_unit_holding_the_server_wants_the_top_weight(self):
        pid = self.home.tmux("display-message", "-p", "#{pid}").out.strip()
        unit = Path(f"/proc/{pid}/cgroup").read_text().strip().rpartition("/")[2]
        box = []
        if not unit:
            # Where the test's cgroup namespace starts at the server's cgroup, no unit is named:
            # a box names one, in the server's own /proc file.
            unit = "acme-server.service"
            named = self.home.root / "server-cgroup"
            named.write_text(f"0::/{SERVICE}/app.slice/{unit}\n")
            box = ["bwrap", "--dev-bind", "/", "/", "--bind", str(named), f"/proc/{pid}/cgroup",
                   "--"]
        self.set_weight(unit, 100)
        self.addCleanup(shutil.rmtree, self.scope(unit))
        done = self.home.run(*box, AK, "orch", "front")
        self.assertEqual((done.code, done.out, done.err), (0, "", ""))
        self.assertEqual(self.weight(unit), 10000)
        self.assertEqual(self.weight(ACME), 100)

    def test_a_pass_with_nothing_changed_asks_nothing_and_a_tick_heals(self):
        self.attach("acme")
        self.wait_weights(10000, 100)
        # A systemctl of this pass's alone: a hook's own pass may still be on its way out.
        alone = self.home.root / "alone"
        alone.mkdir()
        self.addCleanup(shutil.rmtree, alone)
        (alone / "systemctl").write_text(f"#!/bin/sh\ntouch {shlex.quote(str(alone / 'asked'))}\n")
        (alone / "systemctl").chmod(0o755)
        path = f"{alone}{os.pathsep}{self.home.env['PATH']}"
        self.assertEqual(self.home.ak("orch", "front", env={"PATH": path}).code, 0)
        self.assertFalse((alone / "asked").exists())
        self.set_weight(ACME, 100)
        self.set_weight(TWO, 700)
        self.assertEqual(self.home.tick().code, 0)
        self.assertEqual((self.weight(ACME), self.weight(TWO)), (10000, 100))

    def test_a_scope_with_no_weight_file_is_asked_about(self):
        (self.scope(TWO) / "cpu.weight").unlink()
        self.assertEqual(self.home.ak("orch", "front").code, 0)
        self.assertEqual(self.weight(TWO), 100)
        self.assertIn(["--user", "set-property", "--runtime", TWO, "CPUWeight=100"], self.asked())

    def test_no_tree_or_a_failing_systemctl_says_nothing_and_exits_0(self):
        done = self.home.ak("orch", "front", env={"AK_CGROUP_ROOT": str(self.home.root / "none")})
        self.assertEqual((done.code, done.out, done.err), (0, "", ""))
        self.home.fake("systemctl", "#!/bin/sh\necho refused >&2\nexit 1\n")
        self.addCleanup(self.watch_systemctl)
        self.set_weight(ACME, 7)
        done = self.home.ak("orch", "front")
        self.assertEqual((done.code, done.out, done.err), (0, "", ""))
        self.assertEqual(self.weight(ACME), 7)

    def test_no_server_up_is_nothing_to_do(self):
        with Home() as empty:
            done = empty.ak("orch", "front")
            self.assertEqual((done.code, done.out, done.err), (0, "", ""))
            self.assertEqual(empty.calls("systemctl"), [])

    def test_the_accounts_own_seats_are_never_asked_about(self):
        self.attach("acme")
        self.wait_weights(10000, 100)
        self.assertEqual(self.home.ak("orch", "front").code, 0)
        self.assertEqual((self.decoy / "cpu.weight").read_text(), "100\n")
        self.assertNotIn(DECOY, [call[3] for call in self.asked()])


if __name__ == "__main__":
    unittest.main()
