"""A listed machine whose last answer said it is on battery takes no new work, neither a turn nor a
suite's piece, until a check finds it on power: the tick still asks it what it is.

Black-box, on the machine of tests/fixtures/akmachine.py, its work marked: the tick's box holds
the test's own power supplies, a battery, over the host's, so its probe, there and here, answers
by them.  The machine keeps the root of every container it ran: a turn's ends in `-turn`, and the
round's done-when list, placed as a suite is, runs in the others.
"""

from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AMachineOnBatteryIsOfferedNoNewWork(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM acme\n"})
        GitHub(home).grant(self.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       extra='[machines.acme-linux]\nwork = ["turns", "tests"]\n')
        fakeadapter.install(home, claude={"sh": "echo x >x.txt", "final": "## Summary\nedited",
                                          "hand_in": [["done"]]}, codex="pass")
        self.machine = akmachine.install(home, cpus=8)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = self.machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)    # each fake adapter's program, which it never runs
        self.battery = home.root / "power_supply/BAT0"
        self.battery.mkdir(parents=True)
        (self.battery / "type").write_text("Battery\n")

    def checked(self, status):
        """A tick has asked the machine while its battery's status is `status`."""
        (self.battery / "status").write_text(f"{status}\n")
        done = self.home.tick(box=("--ro-bind", self.battery.parent, "/sys/class/power_supply"))
        self.assertEqual(done.code, 0, done.out + done.err)

    def placed(self, title):
        """(turns, other containers) the machine ran for a run of `title`."""
        task = taskfile.write(self.home, self.rig.path, title, done_when=("test -f x.txt",))
        done = self.home.ak("run", str(task), "--no-merge", timeout=300,
                            env={"AK_HOST_READINGS": akmachine.CROWDED})
        self.assertEqual(done.code, 0, done.out + done.err)
        turns = [root.name.endswith("-turn") for root in self.machine.glob("docker/roots/*")]
        shutil.rmtree(self.machine / "docker/roots", ignore_errors=True)
        return turns.count(True), turns.count(False)

    def test_on_battery_it_takes_no_work_until_a_check_finds_it_on_power(self):
        self.checked("Discharging")
        self.assertEqual(self.placed("Add x file"), (0, 0))
        self.checked("Charging")
        self.assertEqual(self.placed("Add x file again"), (2, 1))


if __name__ == "__main__":
    unittest.main()
