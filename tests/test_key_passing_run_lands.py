"""Answer key: a passing run opens its PR, squash-merges the reviewed commit and cleans up.

The executor writes retry.txt and the reviewer passes it, through tests/fixtures/retry's
adapters with no model behind them; GitHub is tests/fixtures/fakegh.py on the rig's bare
origin.  What the run delivered is read off that GitHub, the origin and the disk alone.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, taskfile
from fixtures.akbin import AK, Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

ADAPTERS = Path(__file__).resolve().parent / "fixtures" / "retry"


class PassingRun(unittest.TestCase):
    def test_the_reviewed_commit_is_squash_merged_and_its_branch_and_worktree_go(self):
        home = Home()
        self.addCleanup(home.close)
        rig, gh = Rig(home, "widgets"), GitHub(home)
        akconfig.write(home, ["opus", "astra"])
        task = taskfile.write(home, rig.path, front={"rounds": 1})
        done = home.ak("run", str(task), "--exec", "opus", "--review", "astra",
                       env={"AGENTKIT_ADAPTER_DIR": str(ADAPTERS), "AK_BIN": AK}, timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)

        [pr] = gh.prs()
        run = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((pr["state"], pr["baseRefName"], pr["headRefName"]),
                         ("MERGED", "main", run["branch"]))
        merge = pr["merge"]
        self.assertEqual((merge["method"], merge["match"], merge["head"], merge["deleted"]),
                         ("squash", run["review"]["head_sha"], merge["match"], True))
        self.assertEqual(rig.origin("rev-parse", f"{merge['head']}^{{tree}}"),
                         rig.origin("rev-parse", "main^{tree}"))
        self.assertEqual((rig.head(), rig.origin("show", "main:retry.txt")),
                         (merge["commit"], "hello"))
        self.assertEqual(rig.branches(), ["main"])
        self.assertFalse(Path(run["worktree"]).exists())
        self.assertNotIn(run["branch"], rig.branches(remote=False))


if __name__ == "__main__":
    unittest.main()
