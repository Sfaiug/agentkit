"""Runs of one title started together in one project each get a branch of their own.

Both find `ak/<slug>` free; git makes it for one of them, and the other takes the next name
instead of failing.  Black-box through AK_BIN: a job of two tasks titled alike, with git's
`worktree add -b` held until both runs are at it, so their names always collide.
"""

import json
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# Each `worktree add -b` waits for a second one, 30 s at most: a build that never makes two
# branches at once is not held for good.
HELD = """#!/bin/sh
case " $* " in *" worktree add "*" -b "*)
  touch {held}/$$; n=0
  while [ "$(ls {held} | wc -l)" -lt 2 ] && [ $n -lt 300 ]; do sleep 0.1; n=$((n + 1)); done ;;
esac
exec {git} "$@"
"""


class OneTitleTogether(unittest.TestCase):
    def test_two_runs_of_one_title_started_together_pass_on_branches_apart(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        rig = Rig(home, "widgets")
        held = home.root / "held"
        held.mkdir()
        home.fake("git", HELD.format(held=shlex.quote(str(held)),
                                     git=shlex.quote(shutil.which("git"))))
        tasks = [taskfile.write(home, rig.path, name=f"task-{n}") for n in range(2)]
        done = home.ak("run", *map(str, tasks), "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        states = [json.loads((run / "run.json").read_text()) for run in taskfile.runs(home)]
        self.assertEqual([state["verdict"] for state in states], ["PASS", "PASS"])
        self.assertEqual(sorted(state["branch"] for state in states),
                         ["ak/add-retry-file", "ak/add-retry-file-2"])


if __name__ == "__main__":
    unittest.main()
