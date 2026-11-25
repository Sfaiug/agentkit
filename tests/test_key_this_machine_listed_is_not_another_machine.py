"""A listed machine whose last answer named this host is this machine: it takes no work as another
one, neither a turn nor a suite's piece, nor is asked for its room, until an answer names another
host.  The tick still asks it what it is.

Black-box, as tests/test_key_a_turn_packs_onto_the_busiest_machine.py is: two machines listed,
each a directory with tests/fixtures/akmachine.py's programs that a fake ssh reaches by its name,
writing each line it is given to the machine's `asked`.  acme-self's `hostname` says what this
host's does until the test renames it; being the narrower, a turn would go to it.  Each machine
keeps the root of every container it ran: a turn's ends in `-turn`, and the round's done-when
list, placed as a suite is, runs in the others.
"""

from pathlib import Path
import shutil
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

HARNESSES = (("claude", "1.2.3"), ("codex", "4.5.6"))
CPUS = {"acme-self": 2, "acme-other": 8}
# ssh [OPTION...] [--] NAME LINE: LINE on the machine NAME, its own /run saying it is set up.
SSH = """#!{python}
import os, sys
machine = os.path.join({machines!r}, sys.argv[-2])
if not os.path.isdir(machine):
    sys.exit(255)
with open(os.path.join(machine, "asked"), "a") as asked:
    asked.write(sys.argv[-1].replace("\\n", " ") + "\\n")
os.execve("/bin/bash", ["bash", "-c", sys.argv[-1].replace("/run/", f"{{machine}}/run/")],
          {{"HOME": f"{{machine}}/home", "PATH": f"{{machine}}/bin:/usr/bin:/bin"}})
"""


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ThisMachineListedIsNotAnotherMachine(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM acme\n"})
        GitHub(home).grant(self.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], extra="".join(
            f'[machines.{name}]\nwork = ["turns", "tests"]\n' for name in CPUS))
        fakeadapter.install(home, claude={"sh": "echo x >x.txt", "final": "## Summary\nedited",
                                          "hand_in": [["done"]]}, codex="pass")
        for harness, version in HARNESSES:
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
        self.machines = home.root / "machines"
        for name, count in CPUS.items():
            for directory in ("home", "bin", "docker/images", "docker/containers", "run"):
                (self.machines / name / directory).mkdir(parents=True)
            for tool, text in {**akmachine.TOOLS, "nproc": f"#!/bin/sh\necho {count}\n"}.items():
                (self.machines / name / "bin" / tool).write_text(text)
                (self.machines / name / "bin" / tool).chmod(0o755)
            (self.machines / name / "run/ak-ready").touch()
            for harness, version in HARNESSES:    # each fake adapter's program, which it never runs
                place = self.machines / name / "home/.agentkit-helper/harness" / harness / version
                place.mkdir(parents=True)
                (place / harness).touch(0o755)
        home.fake("ssh", SSH.format(python=sys.executable, machines=str(self.machines)))

    def named(self, host):
        """acme-self's `hostname` says `host`, and a tick has asked both machines."""
        hostname = self.machines / "acme-self/bin/hostname"
        hostname.write_text(f"#!/bin/sh\necho {host}\n")
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        for name in CPUS:
            asked = self.machines / name / "asked"
            self.assertIn("disk_free_mb", asked.read_text(), f"the tick did not ask {name}")
            asked.unlink()
            shutil.rmtree(self.machines / name / "docker/roots", ignore_errors=True)

    def placed(self, title):
        """{machine: (turns, other containers, whether ak asked it anything)} after a run."""
        task = taskfile.write(self.home, self.rig.path, title, done_when=("test -f x.txt",))
        done = self.home.ak("run", str(task), "--no-merge", timeout=300,
                            env={"AK_HOST_READINGS": akmachine.CROWDED})
        self.assertEqual(done.code, 0, done.out + done.err)
        ran = {name: [root.name.endswith("-turn") for root in
                      (self.machines / name / "docker/roots").glob("*")] for name in CPUS}
        return {name: (turns.count(True), turns.count(False),
                       (self.machines / name / "asked").exists())
                for name, turns in ran.items()}

    def test_a_machine_named_as_this_host_takes_no_work_until_named_otherwise(self):
        self.named(socket.gethostname())
        self.assertEqual(self.placed("Add x file"),
                         {"acme-self": (0, 0, False), "acme-other": (2, 1, True)})
        self.named("acme-self")
        self.assertEqual(self.placed("Add x file again"),
                         {"acme-self": (2, 0, True), "acme-other": (0, 1, True)})


if __name__ == "__main__":
    unittest.main()
