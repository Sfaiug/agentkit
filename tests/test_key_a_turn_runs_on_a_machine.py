"""A model turn runs on a machine with room once config.toml says `turns_on_machines = true`, its
results back here when it ends; with the switch off or no room there, it runs here.

Black-box, as tests/test_key_changed_paths_go_with_the_piece.py is, on its machine, which has both
harnesses' programs at the versions here and whose containers have `container=docker` in their
environment: each
harness stand-in writes that to `where` in its out dir, the executor to a commit too.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

WHERE = 'echo "${container:-here}" | tee "${AK_HAND_IN%/*}/where"'
# The executor commits where it ran, leaves left.txt uncommitted and removes gone.txt.
EXECUTE = {"sh": f"{WHERE} >executor.txt && git add executor.txt && git commit -qm where && "
                 "echo left >left.txt && rm gone.txt",
           "final": "## Summary\nedited", "hand_in": [["done"]]}
REVIEW = {"sh": WHERE, "final": "Handed in.", "hand_in": [["done"]]}


class ATurnRunsOnAMachine(unittest.TestCase):
    def run_task(self, switch, cpus):
        """Where the task's turns and its commit ran, and the turn containers the machine ran."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: true\n---\n# widgets\n", "gone.txt": "old\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       settings={"suite_helper": "acme-linux", "turns_on_machines": switch})
        fakeadapter.install(home, claude=EXECUTE, codex=REVIEW)
        machine = akmachine.install(home)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            # each fake adapter's program, which it never runs
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        (machine / "bin/nproc").write_text(f"#!/bin/sh\necho {cpus}\n")
        task = taskfile.write(home, rig.path, done_when=("test -f left.txt && test ! -e gone.txt",))
        done = home.ak("run", str(task), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        state = json.loads((run / "run.json").read_text())
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        # what ran there came home: the uncommitted file, which the loop committed, and the removal
        self.assertEqual(rig.origin("show", "main:left.txt"), "left")
        self.assertNotIn("gone.txt", rig.files())
        turns = sorted(path.read_text().strip() for path in run.rglob("where"))
        containers = len([*machine.glob("docker/roots/*-turn")])
        return turns, rig.origin("show", "main:executor.txt"), containers

    def test_both_turns_run_on_the_machine(self):
        self.assertEqual(self.run_task(True, 2), (["docker"] * 2, "docker", 2))

    def test_with_the_switch_off_or_no_room_the_turns_run_here(self):
        for switch, cpus in ((False, 2), (True, 1)):
            with self.subTest(turns_on_machines=switch, cpus=cpus):
                self.assertEqual(self.run_task(switch, cpus), (["here"] * 2, "here", 0))


if __name__ == "__main__":
    unittest.main()
