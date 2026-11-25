"""A run's row in the history keeps the limits it launched under, whatever the config says later.

The row's `policy` is the run record's, as JSON text with its keys sorted: launched under a config
of `review_rounds = 2` and `rescope_findings = 4`, those two and ak's defaults for the others.
The config changed while the run goes -- stopped in error with its review owed, then resumed under
other numbers -- its row at its end still holds the launch's.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, a config
from akconfig.py and scripted harnesses from fakeadapter.py, and the database is read with
sqlite3, as any other program reads it.
"""

import json
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

LAUNCHED = {"review_rounds": 2, "rescope_findings": 4}
# ak's own numbers for the limits the config leaves unset
DEFAULTS = {"executor_lines": 300, "orchestrator_lines": 50, "extra_rounds": 2}
# The build, then the lock a crashed git leaves: the run ends in error with its review owed.
LOCKED = {"sh": "echo hello > retry.txt && git add -A && git commit -qm 'add retry.txt' && "
                'touch "$(git rev-parse --git-path index.lock)"',
          "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
# The Home's notify sink marks every run a test suite's, which ak never records: these runs go
# without it, as the owner's, and with no webhook configured nothing is posted anywhere.
OWNERS = {"AK_NOTIFY_SINK": None}


def configure(home, settings):
    akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                   settings=settings)


def row(home):
    connection = sqlite3.connect(home.path / ".agentkit/history.db")
    try:
        (found,) = connection.execute("SELECT final_state, policy FROM runs").fetchall()
        return found
    finally:
        connection.close()


class ARunsRowKeepsItsLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        configure(home, LAUNCHED)
        fakeadapter.install(home, claude=LOCKED, codex="pass")
        cls.ran = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", env=OWNERS,
                          timeout=300)
        run_dir = taskfile.only_run(home)
        cls.stopped = row(home)
        worktree = json.loads((run_dir / "run.json").read_text())["worktree"]
        lock = home.run("git", "-C", worktree, "rev-parse", "--path-format=absolute",
                        "--git-path", "index.lock").out.strip()
        Path(lock).unlink()
        configure(home, {"review_rounds": 5, "rescope_findings": 8, "executor_lines": 120})
        cls.resumed = home.ak("run", "resume", run_dir.name, env=OWNERS, timeout=300)
        cls.ended = row(home)

    def test_a_launched_run_s_row_holds_the_config_s_limits_and_ak_s_for_the_rest(self):
        final_state, policy = self.stopped
        self.assertEqual(final_state, "error", self.ran.out + self.ran.err)
        self.assertEqual(policy, json.dumps({**DEFAULTS, **LAUNCHED}, sort_keys=True))

    def test_its_row_at_its_end_still_holds_the_launch_s_after_the_config_changed(self):
        final_state, policy = self.ended
        self.assertEqual(final_state, "pass", self.resumed.out + self.resumed.err)
        self.assertEqual(policy, json.dumps({**DEFAULTS, **LAUNCHED}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
