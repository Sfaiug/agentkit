"""A standby's pass that ends well hands its home back the stamp the home gave it when it began:
where the pass takes its own stamp it asks the home's installed ak, ~/.local/bin/ak, over ssh for
`ak standby --began`, and its last is `ak standby --copied HOST WALL SINCE BOOT no` there, HOST
its own host name and the stamp as printed.  So the home's record of it is that stamp and `no`,
however late the request arrives and whatever the standby's clocks say, and `ak standby` there
names it with its copy's age from that stamp.  A pass whose copy failed hands nothing back.  One
whose home's ak is gone, or answered `--began` with anything but 0 and the line it prints, hands
nothing back either and is, byte for byte, the pass it is against a whole home.  The standby keeps
no record of its own and shows what it showed.  Black-box, through tests/fixtures/twohomes.py,
with each machine's clocks from AK_NOW; the home's ak takes `--copied` at AK_ARRIVES.
"""

from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

RECORDS = ".agentkit/tmp/copies"      # the home's records of the machines that copy it
INSTALLED = ".local/bin/ak"     # the home's installed ak, which install.sh links
STATE = ".agentkit/state/watch.json"     # the home's, which a pass copies
BEGAN = "1789000000 50000 acme-boot-1"      # the home's clocks when a pass begins
NEXT = "1789000120 50120 acme-boot-1"       # when a later pass begins, two minutes on
LATER = "1789000300 50300 acme-boot-1"      # five minutes after BEGAN
# The home's clocks when `--copied` arrives: an hour late, the wall a day back, after a reboot.
ARRIVED = ("1789003600 53600 acme-boot-1", "1788913600 53600 acme-boot-1",
           "1789003600 3600 acme-boot-2")
PASSED = "1789000000 10000 acme-vm-boot-1"     # the standby's clocks during its pass
SHOWN = "1789000300 10300 acme-vm-boot-1"      # five minutes on there
# The standby's clocks during its pass however wrong: the wall a day back, a day on and just
# booted, the home's own boot.
OFF = ("1788913600 10000 acme-vm-boot-1", "1789086400 5 acme-vm-boot-2", BEGAN)
WORDS = "1789000000.0 50000.0 acme-boot-1"      # a stamp, as --began prints one
# Programs at the home's installed ak that never print what --began does and exits 0 by: one to
# each of its outputs and 1, a stamp and 1, two stamp lines and 0, two spaces in one and 0.
BROKEN = ("echo said; echo failed >&2; exit 1", f"echo '{WORDS}'; exit 1",
          f"echo '{WORDS}'; echo '{WORDS}'", f"echo '{WORDS.replace(' ', '  ', 1)}'")


def minutes(count):
    """An age of `count` minutes, a word of its own."""
    return rf"(?<![\w-]){count}m(?![\w-])"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbyTellsItsHome(unittest.TestCase):
    def pair(self, *standbys):
        """A home and its standbys, acme-vm unless named, each its client, the home's ak taking
        `--copied` at the clocks AK_ARRIVES sets there; leaving `with` ends them."""
        machines = Machines("acme-mini", *(standbys or ("acme-vm",)))
        home = machines[0]
        for here in machines[1:]:
            here.client_of(home)
        home.write(STATE, "the home's")
        self.program(home, f'[ "$2" != --copied ] || export AK_NOW="$AK_ARRIVES"\n'
                           f'exec {shlex.quote(home.install.ak)} "$@"')
        return machines

    def program(self, home, script):
        """Put `script` at the home's installed ak, a program logging each request it is given."""
        installed = home.path / INSTALLED
        installed.unlink()
        installed.write_text(f'#!/bin/sh\necho "$*" >>{shlex.quote(str(home.at / "asked"))}\n'
                             f"{script}\n")
        installed.chmod(0o755)

    def passed(self, here, home, began=BEGAN, arrives=ARRIVED[0], now=PASSED):
        """A pass of `here` from `home`, which begins at `began` there and takes `--copied` at
        `arrives`, `here`'s clocks `now`: what it did, as bytes."""
        home.env.update(AK_NOW=began, AK_ARRIVES=arrives)
        here.env["AK_NOW"] = now
        return here.ak("standby", home.name, raw=True)

    def ended(self, here, home, **clocks):
        done = self.passed(here, home, **clocks)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done

    def began(self, home, now=BEGAN):
        """The line `ak standby --began` prints on the home at `now`."""
        home.env["AK_NOW"] = now
        done = home.run(home.install.ak, "standby", "--began", raw=True)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def records(self, home):
        """Each record the home holds, by its host name."""
        return {Path(path).name: data for path, data in home.tree().items()
                if Path(path).parent == Path(RECORDS)}

    def shown(self, machine, now):
        """What `ak standby` on `machine` says at `now`, ending well."""
        machine.env["AK_NOW"] = now
        done = machine.ak("standby")
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def test_the_homes_record_is_the_stamp_it_gave_as_the_pass_began_however_late_it_comes(self):
        for arrives in ARRIVED:
            with self.subTest(arrives=arrives), self.pair() as (home, here):
                self.ended(here, home, arrives=arrives)
                self.assertEqual(self.records(home), {"acme-vm": self.began(home) + b"no\n"})
                [line] = [line for line in self.shown(home, LATER).splitlines()
                          if "acme-vm" in line]
                self.assertRegex(line, minutes(5))

    def test_the_homes_record_is_the_same_whatever_the_standbys_clocks_say(self):
        for now in OFF:
            with self.subTest(now=now), self.pair() as (home, here):
                self.ended(here, home, now=now)
                self.assertEqual(self.records(home), {"acme-vm": self.began(home) + b"no\n"})

    def test_a_pass_whose_copy_failed_leaves_the_record_as_it_was(self):
        with self.pair() as (home, here):
            self.ended(here, home)
            records = self.records(home)
            home.fake("rsync", "#!/bin/sh\nexit 12\n")
            done = self.passed(here, home, began=NEXT)
            self.assertNotEqual(done.code, 0, done.out + done.err)
            self.assertEqual(self.records(home), records)

    def test_a_second_machines_pass_is_listed_beside_the_first(self):
        with self.pair("acme-vm", "acme-mac") as (home, vm, mac):
            self.ended(vm, home)
            self.ended(mac, home, began=NEXT)
            lines = self.shown(home, LATER).splitlines()
        self.assertRegex(next(line for line in lines if "acme-vm" in line), minutes(5))
        self.assertRegex(next(line for line in lines if "acme-mac" in line), minutes(3))

    def test_the_standby_keeps_no_record_and_shows_its_copy_as_it_did(self):
        with self.pair() as (home, here):
            self.ended(here, home)
            self.assertNotIn(RECORDS, here.tree())
            self.assertEqual(self.shown(here, SHOWN),
                             "this machine copies acme-mini: the copy is 5m old\n")

    def test_a_home_whose_ak_does_not_print_its_stamp_is_told_nothing_and_the_pass_is_whole(self):
        with self.pair() as (home, here):
            whole = self.ended(here, home)
        for script in (None, *BROKEN):
            with self.subTest(script=script), self.pair() as (home, here):
                if script:
                    self.program(home, script)
                else:
                    (home.path / INSTALLED).unlink()
                self.assertEqual(self.passed(here, home), whole)
                self.assertEqual(here.tree()[STATE], home.tree()[STATE])
                self.assertRegex(self.shown(here, SHOWN), minutes(5))
                self.assertEqual(self.records(home), {})
                asked = home.root / "asked"
                said = asked.read_text().splitlines() if asked.exists() else []
                self.assertFalse([line for line in said if "--copied" in line.split()], said)


if __name__ == "__main__":
    unittest.main()
