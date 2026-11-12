"""Machines for a standby's keys (tests/fixtures/twohomes.py): two on the one the test runs on,
alike, each with a host name, a home at the other's path, a /tmp and fakes of its own, and
each reaching the other by ssh as the key and the tick reach it."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

REFUSED = "systemctl: not scripted in this test\n"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class TwoHomes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machines = Machines("acme-mini", "acme-vm")
        cls.addClassCleanup(cls.machines.close)
        mini, vm = cls.machines
        cls.pairs = ((mini, vm), (vm, mini))    # each machine with the other

    def test_each_is_its_host_name_and_reaches_the_other_by_it(self):
        for machine, other in self.pairs:
            for argv in (["hostname"],
                         [sys.executable, "-c", "import socket; print(socket.gethostname())"]):
                self.assertEqual(machine.run(*argv).out, f"{machine.name}\n")
            done = machine.run("ssh", "-o", "BatchMode=yes", "-T", other.name, "hostname")
            self.assertEqual((done.code, done.out), (0, f"{other.name}\n"))
            self.assertEqual(machine.run("ssh", "acme-nas", "hostname").code, 255)

    def test_a_command_of_any_length_reaches_the_other_whole(self):
        for machine, other in self.pairs:
            done = machine.run("ssh", other.name, f"printf %s {'x' * 70000} | wc -c", timeout=30)
            self.assertEqual((done.code, done.out.strip()), (0, "70000"), done.err)

    def test_each_has_its_own_files_at_the_one_home(self):
        homes = {machine.run("sh", "-c", 'echo "$HOME"; pwd').out for machine in self.machines}
        self.assertEqual(len(homes), 1, homes)
        self.assertEqual(len(set(homes.pop().split())), 1, "a command starts in its home")
        for machine, other in self.pairs:
            for file in (f"~/from-{machine.name}", f"/tmp/from-{machine.name}"):
                self.assertEqual(machine.run("sh", "-c", f"hostname >{file}").code, 0)
                self.assertNotEqual(other.run("sh", "-c", f"cat {file}").code, 0, file)
                done = other.run("ssh", machine.name, f"cat {file}")
                self.assertEqual(done.out, f"{machine.name}\n", done.err)
            # the test's side of a machine's home is no path on any machine, its own included
            kept = machine.write(f"kept-{machine.name}", "acme\n")
            self.assertEqual(machine.run("cat", kept.name).out, "acme\n")
            for each in self.machines:
                self.assertNotEqual(each.run("cat", kept).code, 0)
                self.assertNotEqual(each.run("ssh", machine.name, f"cat {kept}").code, 0)

    def test_a_fake_is_on_its_machine_alone(self):
        mini, vm = self.machines
        mini.fake("acme-sync", "#!/bin/sh\necho \"acme-sync on $(hostname)\"\n")
        for done in (mini.run("acme-sync"), vm.run("ssh", mini.name, "acme-sync")):
            self.assertEqual(done.out, "acme-sync on acme-mini\n", done.err)
        self.assertNotEqual(vm.run("sh", "-c", "command -v acme-sync").code, 0)

    def test_a_host_tool_is_refused_on_either_side_of_ssh(self):
        for machine, other in self.pairs:
            for done in (machine.run("systemctl", "--user", "start", "acme"),
                         other.run("ssh", machine.name, "systemctl --user start acme")):
                self.assertEqual((done.code, done.err), (1, REFUSED))
        for machine in self.machines:
            self.assertEqual(machine.calls("systemctl"), [["--user", "start", "acme"]] * 2)

    def test_ak_runs_on_each_and_a_tick_writes_in_its_own_home(self):
        mini, vm = self.machines
        for machine in self.machines:
            done = machine.ak("doctor", "-h")
            self.assertEqual(done.code, 0, done.err)
        config = mini.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        theirs = vm.tree()
        done = mini.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(".agentkit/state/watch.json", mini.tree())
        self.assertEqual(vm.tree(), theirs)


if __name__ == "__main__":
    unittest.main()
