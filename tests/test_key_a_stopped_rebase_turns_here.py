"""A turn whose checkout holds a stopped rebase runs here, though `turns_on_machines = true` sends
the run's other turns to a machine with room.

git keeps a stopped rebase in the checkout's own git directory, which no parcel carries: the turn
sent to finish one would find none in the machine's fresh clone.  ak reads that directory's path
whole: read line by line, a newline in it hid the rebase.  No key holds such a path: every review
checkout is git's own `clone --shared`, whose alternates file a newline splits, so no run reaches
the fixer; tests/test_a_stopped_rebase_turns_here.py pins it instead.  Black-box, as
tests/test_key_a_turn_runs_on_a_machine.py is, on its machine: a seat's own PR under `ak run
--review-pr`, as in tests/test_key_own_pr_fix_and_land.py, whose rebase onto main conflicts and
goes to a fixer.  Each harness stand-in writes where it ran to `where` in its out dir.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"'
RESOLVE = {"sh": f"{WHERE} && printf 'main\\nc\\n' > contrib.txt && git add contrib.txt && "
                 "GIT_EDITOR=true git rebase --continue", "final": "Resolved.", "hand_in": [["done"]]}
REVIEW = {"sh": WHERE, "final": "Handed in.", "hand_in": [["done"]]}


class AStoppedRebaseTurnsHere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: test -f contrib.txt\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        gh = GitHub(home)
        akconfig.write(home, ["opus", "astra"],
                       settings={"suite_helper": "acme-linux", "turns_on_machines": True})
        cls.fakes = fakeadapter.install(home, claude=RESOLVE, codex=REVIEW)
        machine = akmachine.install(home)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            # each fake adapter's program, which it never runs
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        Seat(home, "acme", cwd=rig.path, alive=False, record={"workers": ["opus", "astra"]},
             planned=True)
        rig.branch("contrib", {"contrib.txt": "c\n"})
        url = gh.open_pr(rig, "contrib", title="Add contrib")
        rig.commit({"contrib.txt": "main\n"}, "main moves")
        cls.done = home.ak("run", "--review-pr", url, env={"AGENTKIT_SESSION": "acme"},
                           cwd=rig.path, timeout=300)
        cls.state = json.loads((taskfile.only_run(home) / "run.json").read_text())

    def test_the_fixer_finishes_the_rebase_here_after_the_review_ran_on_the_machine(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertEqual(where(self.fakes["codex"].runs()[0]), ("reviewer", "docker"))
        self.assertEqual([where(turn) for turn in self.fakes["claude"].runs()], [("fixer", "here")])
        shown = self.home.run("git", "-C", str(self.rig.bare), "show", "main:contrib.txt")
        self.assertEqual(shown.out, "main\nc\n")


def where(turn):
    """The turn's role and where it ran."""
    return turn["role"], Path(turn["env"]["AK_HAND_IN"]).with_name("where").read_text().strip()


if __name__ == "__main__":
    unittest.main()
