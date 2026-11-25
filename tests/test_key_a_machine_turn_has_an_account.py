"""A turn on a machine runs as the machine's own user, who has an account in its container: the
helper there builds the image for that user, with a recipe that takes the `uid` and `gid` it hands.
A machine whose image has no account for its user takes no turn: it runs here.

Black-box, on the machine of tests/fixtures/akmachine.py as another user than this host's: each
harness stand-in writes where it ran and as whom to `who` in its out dir.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

USER = os.getuid() + 1    # the machine's user and group
WHO = 'echo "${container:-here} $(id -u):$(id -g)" >"${AK_HAND_IN%/*}/who"'
EXECUTE = {"sh": f"{WHO} && echo left >left.txt", "final": "## Summary\nedited",
           "hand_in": [["done"]]}
REVIEW = {"sh": WHO, "final": "Handed in.", "hand_in": [["done"]]}


class AMachineTurnHasAnAccount(unittest.TestCase):
    def run_task(self, recipe):
        """Where a task's turns ran and as whom, and what the machine's images were built for."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": recipe})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       settings={"suite_helper": "acme-linux", "turns_on_machines": True})
        fakeadapter.install(home, claude=EXECUTE, codex=REVIEW)
        machine = akmachine.install(home, user=USER)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            # each fake adapter's program, which it never runs
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        task = taskfile.write(home, rig.path, done_when=("test -f left.txt",))
        done = home.ak("run", str(task), env={"AK_HOST_READINGS": akmachine.CROWDED}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        return (sorted(path.read_text().strip() for path in run.rglob("who")),
                [image.read_text() for image in machine.glob("docker/images/*")])

    def test_a_recipe_that_takes_the_user_gives_the_turns_an_account(self):
        self.assertEqual(self.run_task(akmachine.RECIPE),
                         ([f"docker {USER}:{USER}"] * 2, [f"uid={USER} gid={USER}"]))

    def test_an_image_without_the_user_s_account_leaves_the_turns_here(self):
        # the machine built the image, whose recipe took nothing of the user it was built for
        self.assertEqual(self.run_task("FROM docker.io/library/alpine:3.20\n"),
                         ([f"here {os.getuid()}:{os.getgid()}"] * 2, [""]))


if __name__ == "__main__":
    unittest.main()
