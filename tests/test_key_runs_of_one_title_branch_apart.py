"""Runs of one title started together in one project each get a branch of their own.

Both look for a free `ak/<slug>`; the second takes the next name instead of failing to make the
first's.  Black-box through AK_BIN: a job of two tasks titled alike, with the project's git
holding the first `ak/` branch it makes for a moment, its name looked at and not yet made.
"""

import json
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# git runs it on each ref change; only the first in `ak/` waits, which `mkdir` claims once
HELD = """#!/bin/sh
if [ "$1" = prepared ] && grep -q ' refs/heads/ak/' && mkdir {held} 2>/dev/null; then sleep 2; fi
"""


class OneTitleTogether(unittest.TestCase):
    def test_two_runs_of_one_title_started_together_pass_on_branches_apart(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        rig = Rig(home, "widgets")
        hook = rig.path / ".git/hooks/reference-transaction"
        hook.write_text(HELD.format(held=shlex.quote(str(home.root / "held"))))
        hook.chmod(0o755)
        tasks = [taskfile.write(home, rig.path, name=f"task-{n}") for n in range(2)]
        done = home.ak("run", *map(str, tasks), "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue((home.root / "held").is_dir())
        states = [json.loads((run / "run.json").read_text()) for run in taskfile.runs(home)]
        self.assertEqual([state["verdict"] for state in states], ["PASS", "PASS"])
        self.assertEqual(sorted(state["branch"] for state in states),
                         ["ak/add-retry-file", "ak/add-retry-file-2"])


if __name__ == "__main__":
    unittest.main()
