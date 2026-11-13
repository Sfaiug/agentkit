"""A follow-up's check runs without the `timeout N` its reviewer began the proof with.

A reviewer begins most proofs with `timeout N`, and a follow-up's check is its proof: the line
its seat's plan gets runs it, and so does the done-when of its fix run.  Each has a bound of
ak's own, and on a loaded host a right fix ran past the reviewer's, which ended its fix run
blocked.  So the check is the proof without the bound it begins with, a unit after the number
or not; a proof that itself ended in 124 keeps its bound, which there is what fails.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, from a
seat of akseat.py, against the origin of gitrig.py and the GitHub of fakegh.py, with scripted
harnesses from fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import re
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PLAN_LINE, Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# each proof the reviewer hands in, at a line of its own, and the check its plan line gets
CHECKS = {"timeout 120 test -f sturdy.txt": "test -f sturdy.txt",
          "timeout 15s test -f strong.txt": "test -f strong.txt",
          "timeout 1 sleep 60": "timeout 1 sleep 60"}     # ends in 124
WORK = {**fakeadapter.WORK, "write": {"retry.txt": "one\ntwo\nthree\n"}}
REVIEW = {"final": "Three more defects.", "hand_in": [
    *(["follow-up", f"retry.txt:{line}", f"flimsy widget {line}", "it breaks later",
       "--run", proof] for line, proof in enumerate(CHECKS, 1)),
    ["done"]]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AFollowUpCheckWithoutItsReviewersBound(unittest.TestCase):
    def test_each_plan_line_s_check_is_its_proof_less_a_bound_that_did_not_fail(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        Seat(home, "acme", cwd=rig.path, record={"reviewers": ["astra"]}, planned=True)
        release = home.root / "adapters" / "release"
        # the executor's turn waits for the test to let it go, at most 100 s
        held = (f"i=0; while [ ! -f {shlex.quote(str(release))} ] && [ $i -lt 1000 ]; "
                "do sleep 0.1; i=$((i+1)); done")
        fakes = fakeadapter.install(home, claude={"sh": held, **WORK}, codex=REVIEW)
        task = taskfile.write(home, rig.path, "Add retry file")
        run = home.spawn("run", str(task), env={"AGENTKIT_SESSION": "acme"})
        # The owner unmarks the seat's executors while its run is in flight: each line is then
        # the seat's own to build, and no fix run is left going.
        deadline = time.monotonic() + 600
        while not fakes["claude"].n and run.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        record = home.path / ".agentkit/state/session-acme.json"
        record.write_text(json.dumps({**json.loads(record.read_text()), "workers": []}))
        release.write_text("")
        self.assertEqual(run.wait(600), 0, home.log("spawn-1.err").read_text())
        plan = (home.path / ".agentkit/state/plan-acme.md").read_text()
        self.assertEqual(re.findall(r" · check: `([^`]+)` · ", plan.replace(PLAN_LINE + "\n", "")),
                         list(CHECKS.values()))


if __name__ == "__main__":
    unittest.main()
