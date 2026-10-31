"""A model turn goes to the machine with the least room that still takes it, passing over one ak
rents that Google ends within the hour a turn is lent a login for, and placing it asks Google
nothing; a suite still goes to the machine with the most room.

Black-box, as tests/test_key_a_turn_runs_on_a_machine.py is, on machines with
tests/fixtures/akmachine.py's programs and CPUs of their own, each a directory a fake ssh reaches by
its name; those ak rents are listed by tests/fixtures/google.py and served by a tick. Each machine
keeps the root of every container it ran: a turn's ends in `-turn`, and the round's done-when list,
placed as a suite is, runs in the others.
"""

from datetime import UTC, datetime
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home, boxable
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from fixtures.google import SKUS, Google, kind

HARNESSES = (("claude", "1.2.3"), ("codex", "4.5.6"))
# ssh [OPTION...] [--] NAME LINE: LINE on the machine NAME, its own /run saying it is set up.
SSH = """#!{python}
import os, sys
machine = os.path.join({machines!r}, sys.argv[-2])
if not os.path.isdir(machine):
    sys.exit(255)
os.execve("/bin/bash", ["bash", "-c", sys.argv[-1].replace("/run/", f"{{machine}}/run/")],
          {{"HOME": f"{{machine}}/home", "PATH": f"{{machine}}/bin:/usr/bin:/bin"}})
"""


def listed(n, name, life):
    """Google's listing of a machine ak rented a minute ago, living `life` seconds."""
    return {"id": str(n), "name": name, "labels": {"ak": "rented"},
            "creationTimestamp": datetime.fromtimestamp(time.time() - 60, UTC).isoformat(),
            "machineType": "zones/europe-west4-a/machineTypes/c4a-standard-8",
            "scheduling": {"maxRunDuration": {"seconds": str(life)}},
            "networkInterfaces": [{"accessConfigs": [{"natIP": f"203.0.113.{n}"}]}]}


class ATurnPacksOntoTheBusiestMachine(unittest.TestCase):
    def placed(self, cpus, lives=None):
        """{machine: (turns, other containers)} after a task's run on machines of `cpus`, {name:
        CPUs}: those `lives` names ak rents, {name: seconds Google lets it live}, the others named
        under `[machines]`; and what Google was asked while it ran."""
        home, lives = Home(), lives or {}
        self.addCleanup(home.close)
        google = Google(home, [SKUS], [{"zones/europe-west4-a": {
            "machineTypes": [kind("c4a-standard-8", 8, 32)]}}])
        self.addCleanup(google.close)
        google.key()
        env = {"AK_GOOGLE_URL": google.env["AK_GOOGLE_URL"]}
        rig = Rig(home, "widgets", files={"AGENTS.md": "---\ntests: true\n---\n# widgets\n",
                                          "tools/helper/Containerfile": "FROM acme\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], settings={"turns_on_machines": True}, extra="".join(
            f"[machines.{name}]\n" for name in cpus if name not in lives)
            + "[google_cloud]\nactive = true\nmax_month = 50\n")
        fakeadapter.install(home, claude={"sh": "echo x >x.txt", "final": "## Summary\nedited",
                                          "hand_in": [["done"]]}, codex="pass")
        for harness, version in HARNESSES:
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
        machines = home.root / "machines"
        for name, count in cpus.items():
            for directory in ("home", "bin", "docker/images", "docker/containers", "run"):
                (machines / name / directory).mkdir(parents=True)
            for tool, text in {**akmachine.TOOLS, "nproc": f"#!/bin/sh\necho {count}\n"}.items():
                (machines / name / "bin" / tool).write_text(text)
                (machines / name / "bin" / tool).chmod(0o755)
            (machines / name / "run/ak-ready").touch()
            for harness, version in HARNESSES:    # each fake adapter's program, which it never runs
                place = machines / name / "home/.agentkit-helper/harness" / harness / version
                place.mkdir(parents=True)
                (place / harness).touch(0o755)
        home.fake("ssh", SSH.format(python=sys.executable, machines=str(machines)))
        if lives:    # the first tick keeps the prices they cost, the second serves them
            for listing in [], [listed(n, name, life)
                                for n, (name, life) in enumerate(lives.items(), 1)]:
                google.machines = listing
                done = home.tick(env=env)
                self.assertEqual(done.code, 0, done.out + done.err)
        asked = len(google.asked)
        task = taskfile.write(home, rig.path, done_when=("test -f x.txt",))
        done = home.ak("run", str(task), env=env, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        turns = {name: [root.name.endswith("-turn") for root in
                        (machines / name / "docker/roots").glob("*")] for name in cpus}
        return ({name: (ran.count(True), ran.count(False)) for name, ran in turns.items()},
                google.asked[asked:])

    def test_a_turn_goes_to_the_machine_with_the_least_room_that_takes_it(self):
        self.assertEqual(self.placed({"acme-wide": 8, "acme-narrow": 2}),
                         ({"acme-wide": (0, 1), "acme-narrow": (2, 0)}, []))

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_turn_passes_over_a_rented_machine_that_ends_within_the_hour(self):
        self.assertEqual(self.placed({"acme-wide": 8, "acme-soon": 2, "acme-later": 4},
                                     {"acme-soon": 1800, "acme-later": 21600}),
                         ({"acme-wide": (0, 1), "acme-soon": (0, 0), "acme-later": (2, 0)}, []))


if __name__ == "__main__":
    unittest.main()
