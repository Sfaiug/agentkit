"""A suite's pieces read the test-times record from the file AK_TIMES names, however long it is:
past the 131,072 bytes Linux holds in one argument or one variable, the suite still goes to the
suite helper, and still starts here.

Black-box: the program `AK_BIN` names runs a task from outside through tests/fixtures/akbin.py,
against the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from
fakeadapter.py; ssh runs what it is given on `acme-linux`, the Linux machine of
tests/fixtures/akmachine.py, and this host takes no turn of its own (`AK_MAX_RUNS=0`). The record
is the one ak keeps from the lines of the task's own check, which runs the suite whole, never
planted.
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

PARTS = 2000
# 2,000 entries of `"suite.sh::part-0001-xx…": 1.0, ` hold 162,000 bytes, past 131,072.
PART = "part-%04d-" + "x" * 52
# Each piece of the landing's suite logs its share and the parts the record in the file AK_TIMES
# names holds, in its clone's Git storage; then it, and the task's own check (`check`, which a
# helper runs as a piece too), pass each part as suite_times.passed prints it.
SUITE_SH = ('[ -n "$1" ] || echo "$AK_SHARD" "$(grep -o "suite\\.sh::" "$AK_TIMES" | wc -l)"'
            ' >>"$(git rev-parse --git-common-dir)/suite.log"\n'
            f"awk 'BEGIN {{ for (i = 1; i <= {PARTS}; i++)"
            f' printf "PASS  suite.sh::{PART} (1.0s)\\n", i }}\'\n')
EDIT = {"write": {"retry.txt": "hello\n", "widget.txt": "v2\n"}, "commit": "edit",
        "final": "## Summary\nedited", "hand_in": [["done"]]}


class SuiteDataPastOneArgument(unittest.TestCase):
    def run_task(self, helper=True):
        """Runs the task on a project whose suite is SUITE_SH, with `helper` acme-linux as its
        suite helper: the landing's pieces' logged [share, parts], there or, with none, here."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": '---\nhealth: none\ntests: : "$AK_SHARD"; sh suite.sh\n---\n# widgets\n',
            "suite.sh": SUITE_SH, "widget.txt": "v1\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       settings={"suite_helper": "acme-linux"} if helper else None)
        fakeadapter.install(home, claude=EDIT, codex="work")
        machine = akmachine.install(home)
        task = taskfile.write(home, rig.path, done_when=("test -f retry.txt && sh suite.sh check",))
        done = home.ak("run", str(task), timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        logs = (machine.glob("docker/roots/*/home/ak/work/.git/suite.log") if helper else
                [rig.path / ".git/suite.log"])
        return [line.split() for log in logs if log.is_file()
                for line in log.read_text().splitlines()]

    def test_the_landing_s_pieces_read_the_whole_record_on_the_helper(self):
        logged = self.run_task()
        self.assertEqual(sorted(logged), [["1/2", str(PARTS)], ["2/2", str(PARTS)]], logged)

    def test_the_landing_s_suite_reads_the_whole_record_here(self):
        logged = self.run_task(helper=False)
        self.assertTrue(logged, logged)
        self.assertEqual({line[1] for line in logged}, {str(PARTS)}, logged)


if __name__ == "__main__":
    unittest.main()
