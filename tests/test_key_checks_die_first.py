"""When memory runs out, the kernel ends a check before any harness or ak itself.

Every command a check box runs, a done-when check and each child it starts, reads 1000 in
`/proc/self/oom_score_adj`, the score the kernel's OOM killer ends first.  The ak process that
ran it keeps its own: the reviewer turn it starts after the check reads the score ak was started
with.  Where the score cannot be written, here a box with no /proc, the checks still run and
pass or fail as before.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py with scripted harnesses from fakeadapter.py.
"""

import json
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, SYSTEM
from fixtures.gitrig import Rig

SCORE = ("read own </proc/self/oom_score_adj; child=$(sh -c 'cat /proc/self/oom_score_adj'); "
         "echo \"check $own child $child\"; test -f retry.txt")
PASSING = "test ! -e /proc/self/oom_score_adj && test -f retry.txt"
FAILING = "echo 'other.txt is missing'; test -f other.txt"
MINE = Path("/proc/self/oom_score_adj").read_text().strip()
# A bwrap giving each box an empty /proc, where no score can be written; a box that starts a
# box of its own, as ak's probe does, keeps it for the box inside.
NO_PROC = """#!/bin/bash
for ((at = 1; at <= $#; at++)); do [[ ${!at} == -- ]] && break; done
next=$((at + 1))
[[ ${!next} == bwrap ]] || set -- "${@/#--proc/--tmpfs}"
exec %s "$@"
"""


def run(home, done_when):
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus", "astra"])
    fakes = fakeadapter.install(home, claude="work", codex="pass")
    fakes["codex"].behave({**fakeadapter.PASS,
                           "sh": f"cat /proc/self/oom_score_adj > {fakes['codex'].dir}/score"})
    task = taskfile.write(home, rig.path, done_when=done_when, front={"rounds": 1})
    done = home.ak("run", str(task), "--no-merge", timeout=300)
    run_dir = taskfile.only_run(home)
    return (done, json.loads((run_dir / "run.json").read_text()),
            (run_dir / "round-1/donewhen.log").read_text(), fakes)


class ChecksDieFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.done, cls.state, cls.log, cls.fakes = run(cls.home, (SCORE,))

    def test_a_check_and_its_child_read_the_score_ended_first(self):
        self.assertEqual(self.state.get("verdict"), "PASS", self.done.out + self.done.err)
        self.assertIn(f"$ {SCORE}\n[exit 0]\ncheck 1000 child 1000\n", self.log)

    def test_the_ak_that_ran_the_check_keeps_its_own_score(self):
        self.assertEqual((self.fakes["codex"].dir / "score").read_text().strip(), MINE)


class UnwritableScore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.fake("bwrap", NO_PROC % shutil.which("bwrap", path=":".join(SYSTEM)))
        cls.done, cls.state, cls.log, _ = run(cls.home, (PASSING, FAILING))

    def test_the_checks_run_and_pass_or_fail_as_before(self):
        self.assertEqual(self.state.get("verdict"), "FAIL", self.done.out + self.done.err)
        self.assertIn(f"$ {PASSING}\n[exit 0]", self.log)
        self.assertIn(f"$ {FAILING}\n[exit 1]\nother.txt is missing", self.log)


if __name__ == "__main__":
    unittest.main()
