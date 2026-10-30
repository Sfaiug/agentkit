"""A model turn runs on a machine with room once config.toml says `machine_turns = true`, its
results back here when it ends; with the switch off, no room there or no program, it runs here.

Black-box, as tests/test_key_changed_paths_go_with_the_piece.py is, on its machine, which has both
harnesses' programs and whose containers have `container=docker` in their environment: each
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
UPTIME = "#!/bin/sh\necho ' 12:00:00 up 1 day,  load average: {}, 0.00, 0.00'\n"


class ATurnRunsOnAMachine(unittest.TestCase):
    def run_task(self, switch, load, program=True):
        """Where the task's turns and its commit ran, and the turn containers the machine ran."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: true\n---\n# widgets\n", "gone.txt": "old\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       settings={"suite_helper": "acme-linux", "machine_turns": switch})
        fakeadapter.install(home, claude=EXECUTE, codex=REVIEW)
        machine = akmachine.install(home)
        for harness in ("claude", "codex"):    # each fake adapter's program, which it never runs
            place = machine / "home/.agentkit-helper/harness" / harness
            place.mkdir(parents=True)
            (place / harness).touch(0o755 if program else 0o644)
        (machine / "bin/uptime").write_text(UPTIME.format(load))
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
        self.assertEqual(self.run_task(True, "0.00"), (["docker"] * 2, "docker", 2))

    def test_with_the_switch_off_no_room_or_no_program_the_turns_run_here(self):
        for switch, load, program in ((False, "0.00", True), (True, "2.00", True),
                                      (True, "0.00", False)):
            with self.subTest(machine_turns=switch, load=load, program=program):
                self.assertEqual(self.run_task(switch, load, program), (["here"] * 2, "here", 0))


if __name__ == "__main__":
    unittest.main()
