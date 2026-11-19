"""A follow-up's check runs without the `timeout N` its reviewer began the proof with.

A reviewer begins most proofs with `timeout N`, and a follow-up's check is its proof: the
done-when of its fix run runs it.  That has a bound of ak's own, and on a loaded host a right
fix ran past the reviewer's, which ended its fix run blocked.  So the check is the proof
without the bound it begins with, a unit after the number or not; a proof that itself ended in
124 keeps its bound, which there is what fails.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from a
seat of akseat.py, against the origin of gitrig.py and the GitHub of fakegh.py, with scripted
harnesses from fakeadapter.py; this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_a_follow_up_is_no_plan_line import alive, held, state

# each proof the reviewer hands in, at a line of its own, and the check its fix run gets
CHECKS = {"timeout 120 test -f sturdy.txt": "test -f sturdy.txt",
          "timeout 15s test -f strong.txt": "test -f strong.txt",
          "timeout 1 sleep 60": "timeout 1 sleep 60"}     # ends in 124
WORK = {**fakeadapter.WORK, "write": {"retry.txt": "one\ntwo\nthree\n"}}
REVIEW = {"final": "Three more defects.", "hand_in": [
    *(["follow-up", f"retry.txt:{line}", f"flimsy widget {line}", "it breaks later",
       "--run", proof] for line, proof in enumerate(CHECKS, 1)),
    ["done"]]}
DONE_WHEN = re.compile(r"## Done when\n```bash\n(.*)\n```")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AFollowUpCheckWithoutItsReviewersBound(unittest.TestCase):
    def test_each_fix_run_s_check_is_its_proof_less_a_bound_that_did_not_fail(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        Seat(home, "acme", cwd=rig.path, record={"reviewers": ["astra"]}, planned=True)
        release = home.root / "adapters" / "release"
        # Each fix run's turn waits for the test, so what the merge started is still there to read.
        fakeadapter.install(home, claude=[WORK, held(release, fakeadapter.PASS)], codex=REVIEW)
        task = taskfile.write(home, rig.path, "Add retry file")
        done = home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"}, timeout=600)
        self.addCleanup(settle, home, release)
        self.assertEqual(done.code, 0, done.out + done.err)
        [parent] = [run for run in taskfile.runs(home) if not state(run).get("followup")]
        fixes = [parent.parent / name for name in state(parent).get("followup_runs") or []]
        self.assertEqual([DONE_WHEN.search((fix / "task.md").read_text())[1] for fix in fixes],
                         list(CHECKS.values()))


def settle(home, release):
    # A fix run still going would outlive this Home, so each ends before the Home goes.
    for run in taskfile.runs(home):
        if alive(state(run).get("pid")):
            home.ak("run", "stop", run.name)
    release.write_text("")


if __name__ == "__main__":
    unittest.main()
