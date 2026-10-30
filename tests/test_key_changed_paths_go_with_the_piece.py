"""A round's suite narrowed to its change runs its pieces on the suite helper, each reading the
change's paths from the file AK_CHANGED names there.

The helper hands a piece no environment: the paths go in its command, as AK_TIMES does.
Black-box: the program `AK_BIN` names runs a task from outside through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from
fakeadapter.py; ssh runs what it is given on `acme-linux`, the Linux machine of
tests/fixtures/akmachine.py, and this host takes no turn of its own (`AK_MAX_RUNS=0`).
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

# Each piece logs its share and the paths the file it is given lists, in its clone's Git storage.
SUITE_SH = ('echo "$AK_SHARD" $(cat "${1:-/dev/null}")'
            ' >>"$(git rev-parse --git-common-dir)/suite.log"\n')
EDIT = {"write": {"retry.txt": "hello\n", "widget.txt": "v2\n"}, "commit": "edit",
        "final": "## Summary\nedited", "hand_in": [["done"]]}


class ChangedPathsGoWithThePiece(unittest.TestCase):
    def test_a_round_s_pieces_read_the_change_s_paths_on_the_helper(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": '---\ntests: : "$AK_SHARD"; sh suite.sh "$AK_CHANGED"\n---\n# widgets\n',
            "suite.sh": SUITE_SH, "widget.txt": "v1\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], settings={"suite_helper": "acme-linux"})
        fakeadapter.install(home, claude=EDIT, codex="work")
        machine = akmachine.install(home)
        done = home.ak("run", str(taskfile.write(home, rig.path)), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        there = [line for log in machine.glob("docker/roots/*/home/ak/work/.git/suite.log")
                 for line in log.read_text().splitlines()]
        # the landing's suite runs there too, AK_CHANGED naming nothing
        self.assertEqual(sorted(line for line in there if " " in line),
                         ["1/2 retry.txt widget.txt", "2/2 retry.txt widget.txt"], there)


if __name__ == "__main__":
    unittest.main()
