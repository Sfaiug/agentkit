"""A model turn runs here while this host has room for it, though a machine marked for turns has
room too; with this host short of processors, or of memory, it goes to that machine, and with both
full it runs here.

Black-box, on the machine of tests/fixtures/akmachine.py, marked for turns under `[machines]`, full
with one CPU, as a turn takes two: each harness stand-in writes where it ran to `where` in its out
dir, `docker` in the machine's containers. This host's readings are injected: 32000 MiB, of which a
run needs 6400 free to be admitted (config.min_free_mb), and a turn's 4096 more to stay here.
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

WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"'


def host(load=0, free_mb=16000):
    return json.dumps({"cpus": 4, "load": load, "free_mb": free_mb, "mem_total_mb": 32000})


class ATurnStaysHomeWhileHomeHasRoom(unittest.TestCase):
    def where(self, readings, cpus=2):
        """Where a task's executor and reviewer ran, with this host's `readings` and a machine of
        `cpus` CPUs."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": akmachine.RECIPE})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], extra='[machines.acme-linux]\nwork = ["turns"]\n')
        fakeadapter.install(home, claude={"sh": f"{WHERE}; echo x >x.txt",
                                          "final": "## Summary\nedited", "hand_in": [["done"]]},
                            codex={"sh": WHERE, "final": "Handed in.", "hand_in": [["done"]]})
        machine = akmachine.install(home, cpus=cpus)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            # each fake adapter's program, which it never runs
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        task = taskfile.write(home, rig.path, done_when=("test -f x.txt",))
        done = home.ak("run", str(task), env={"AK_HOST_READINGS": readings}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        return [path.read_text().strip() for path in taskfile.only_run(home).rglob("where")]

    def test_a_calm_home_keeps_the_turns_though_the_machine_has_room(self):
        self.assertEqual(self.where(host()), ["here"] * 2)

    def test_a_home_short_of_processors_sends_them_to_the_machine(self):
        self.assertEqual(self.where(host(load=2.5)), ["docker"] * 2)

    def test_a_home_short_of_memory_sends_them_to_the_machine(self):
        # a run is admitted with 10000 free, but a turn's 4096 would leave less than its 6400
        self.assertEqual(self.where(host(free_mb=10000)), ["docker"] * 2)

    def test_with_both_full_they_run_here(self):
        self.assertEqual(self.where(akmachine.CROWDED, cpus=1), ["here"] * 2)


if __name__ == "__main__":
    unittest.main()
