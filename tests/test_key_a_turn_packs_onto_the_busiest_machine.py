"""A model turn this crowded host hands on goes to the machine with the least room that still takes
it; a suite still goes to the machine with the most room.

Black-box, as tests/test_key_a_turn_runs_on_a_machine.py is, on machines with
tests/fixtures/akmachine.py's programs and CPUs of their own, each a directory a fake ssh reaches by
its name. Each machine keeps the root of every container it ran: a turn's ends in `-turn`, and the
round's done-when list, placed as a suite is, runs in the others.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

HARNESSES = (("claude", "1.2.3"), ("codex", "4.5.6"))
# ssh [OPTION...] [--] NAME LINE: LINE on the machine NAME.
SSH = """#!{python}
import os, sys
machine = os.path.join({machines!r}, sys.argv[-2])
if not os.path.isdir(machine):
    sys.exit(255)
os.execve("/bin/bash", ["bash", "-c", sys.argv[-1]],
          {{"HOME": f"{{machine}}/home", "PATH": f"{{machine}}/bin:/usr/bin:/bin"}})
"""


class ATurnPacksOntoTheBusiestMachine(unittest.TestCase):
    def placed(self, cpus):
        """{machine: (turns, other containers)} after a task's run on the machines of `cpus`,
        {name: CPUs}, each named under `[machines]`."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={"AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
                                          "tools/helper/Containerfile": "FROM acme\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], settings={"turns_on_machines": True},
                       extra="".join(f"[machines.{name}]\n" for name in cpus))
        fakeadapter.install(home, claude={"sh": "echo x >x.txt", "final": "## Summary\nedited",
                                          "hand_in": [["done"]]}, codex="pass")
        for harness, version in HARNESSES:
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
        machines = home.root / "machines"
        for name, count in cpus.items():
            for directory in ("home", "bin", "docker/images", "docker/containers"):
                (machines / name / directory).mkdir(parents=True)
            for tool, text in {**akmachine.TOOLS, "nproc": f"#!/bin/sh\necho {count}\n"}.items():
                (machines / name / "bin" / tool).write_text(text)
                (machines / name / "bin" / tool).chmod(0o755)
            for harness, version in HARNESSES:    # each fake adapter's program, which it never runs
                place = machines / name / "home/.agentkit-helper/harness" / harness / version
                place.mkdir(parents=True)
                (place / harness).touch(0o755)
        home.fake("ssh", SSH.format(python=sys.executable, machines=str(machines)))
        task = taskfile.write(home, rig.path, done_when=("test -f x.txt",))
        done = home.ak("run", str(task), env={"AK_HOST_READINGS": akmachine.CROWDED}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        turns = {name: [root.name.endswith("-turn") for root in
                        (machines / name / "docker/roots").glob("*")] for name in cpus}
        return {name: (ran.count(True), ran.count(False)) for name, ran in turns.items()}

    def test_a_turn_goes_to_the_machine_with_the_least_room_that_takes_it(self):
        self.assertEqual(self.placed({"acme-wide": 8, "acme-narrow": 2}),
                         {"acme-wide": (0, 1), "acme-narrow": (2, 0)})


if __name__ == "__main__":
    unittest.main()
