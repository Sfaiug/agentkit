"""A review of a seat's own PR whose fixer ran dry carries on once its model can run.

A FAIL on a seat's own PR is fixed by the model that wrote it, the seat's orchestrator, which
need be none of the seat's workers.  When that fixer's provider refuses it for usage and no
worker on another provider can take the turn, the run parks `exhausted` on it; once the
provider answers again, a dry tick says it would resume the run, and `ak run resume` from the
seat carries the review on to its merge with the fixer on the orchestrator's model.  Until 13
Nov 2026 the tick and the seat's resume both refused it as a model outside the run (`'opus' is
not a worker of session 'acme'`).  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, as tests/test_key_own_pr_fix_and_land.py runs a seat's own PR.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_own_pr_fix_and_land import FIND, FIX, RULES

# refused with a moment ten seconds on, which ak reads against the real clock
REFUSED = {"final": "You have hit your usage limit. Try again at {in 10}.", "exit": 1}


class FixerRanDry(unittest.TestCase):
    """The acme seat's orchestrator is opus; its one worker, fable, is on opus's provider and
    reviews, so no worker can take a turn opus's provider refuses."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets", files={"AGENTS.md": RULES})
        gh = GitHub(home)
        akconfig.write(home, ["fable", "opus"])
        cls.fakes = fakeadapter.install(home, claude=[FIND, REFUSED, FIX, "pass"])
        Seat(home, "acme", cwd=rig.path, alive=False, record={"workers": ["fable"]},
             planned=True)
        rig.branch("contrib", {"contrib.txt": "c\n"})
        seat = {"env": {"AGENTKIT_SESSION": "acme"}, "cwd": rig.path}
        cls.ran = home.ak("run", "--review-pr", gh.open_pr(rig, "contrib", title="Add contrib"),
                          timeout=300, **seat)
        back = time.time() + 11
        cls.run_dir = taskfile.only_run(home)
        cls.parked = json.loads((cls.run_dir / "run.json").read_text())
        time.sleep(max(0, back - time.time()))
        cls.tick = home.ak("watch", "--dry-run")
        cls.resumed = home.ak("run", "resume", cls.run_dir.name, timeout=300, **seat)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.opus = akconfig.read(home)["models"]["opus"]["model"]

    def test_the_fixer_s_refusal_parks_the_run_on_its_writer(self):
        self.assertEqual(self.ran.code, 1, self.ran.out + self.ran.err)
        self.assertEqual((self.parked["state"], self.parked["executor"]), ("exhausted", "opus"))

    def test_a_dry_tick_would_resume_it_once_its_provider_answers(self):
        self.assertIn(f"would resume {self.run_dir.name}: anthropic window refilled",
                      self.tick.out.splitlines(), self.tick.out + self.tick.err)

    def test_the_seat_resumes_it_and_the_fixer_runs_on_the_orchestrator_s_model(self):
        self.assertEqual(self.resumed.code, 0, self.resumed.out + self.resumed.err)
        fixers = [turn for turn in self.fakes["claude"].runs() if turn["role"] == "fixer"]
        self.assertEqual([turn["argv"][0] for turn in fixers], [self.opus] * 2)
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))


if __name__ == "__main__":
    unittest.main()
