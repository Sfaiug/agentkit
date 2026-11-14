"""A merge GitHub answers `Merge already in progress` for is waited for, and counts once made.

A merge call GitHub answered with a 5xx may be under way there, and asked again GitHub answers
`GraphQL: Merge already in progress (mergePullRequest)`.  On 13 Nov 2026 a run ended PASS, not
merged, on that answer while GitHub finished the merge 44 seconds later, and the 17 members of
its line behind it went back to the line.  Now that answer takes the 5xx's road: the wait, the
re-fetch, the PR read again, merged there and the run is merged.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, against the bare origin of gitrig.py and
the GitHub of fakegh.py, whose first `pr merge` answers that the merge is in progress and makes
it LATER seconds on, with scripted harnesses from fakeadapter.py.  ak waits its least retry wait,
a minute, before reading the PR again (there is no seam to shorten it), so this file takes a
little over a minute.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# Seconds after its answer that GitHub has the merge made: past the reads of the PR a run makes
# straight after the answer, well within ak's least wait, a minute, as host load goes.
LATER = 20
# The first `pr merge`, answered at once and made at GitHub LATER seconds on; fakegh logs the
# one call as it logs every call.
MAKING = """#!/bin/sh
if [ "$1 $2" = "pr merge" ] && [ ! -e {asked} ]; then
  : >{asked}
  (sleep {later}; {github}) </dev/null >/dev/null 2>&1 &
  echo 'GraphQL: Merge already in progress (mergePullRequest)' >&2
  exit 1
fi
exec {github}
"""


class AMergeGitHubIsStillMakingIsWaitedFor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        cls.gh = GitHub(home)
        cls.gh.grant(rig.slug, "WRITE")
        github = (home.bin / "gh").read_text().splitlines()[1].removeprefix("exec ")
        home.fake("gh", MAKING.format(asked=shlex.quote(str(home.root / "merge-asked")),
                                      later=LATER, github=github))
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        cls.done = home.ak("run", str(taskfile.write(home, rig.path, "Add retry file")), timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_the_run_ends_pass_merged(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        last = self.done.out.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.endswith(f"PASS, merged -> {self.run_dir / 'result.md'}"), last)
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "merged")},
                         {"state": "pass", "verdict": "PASS", "merged": True})

    def test_the_merge_github_was_making_is_not_asked_for_again(self):
        merges = [call for call in self.home.calls("gh") if call[:2] == ["pr", "merge"]]
        self.assertEqual(len(merges), 1, merges)
        self.assertEqual(self.gh.pr(1)["state"], "MERGED")


if __name__ == "__main__":
    unittest.main()
