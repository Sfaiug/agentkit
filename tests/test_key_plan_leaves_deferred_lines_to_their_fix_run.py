"""A seat's plan verification leaves a deferred line to its fix run while that run is queued or
running, and checks it as any line while that run is paused or once it ended unmerged.

A review follow-up's line waits for a fix run carrying its check, whose delivery checks it
anyway; running such proofs at every verification made most of an hour-long one.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py in a seat's
environment, over a project tests/fixtures/gitrig.py keeps, beside a run record written where
ak reads it; each check appends to a file as it runs, and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

SEAT = "fix-api"
# each fails, so its line stays open and is checked at every verification that takes it in
DEFERRED = 'echo ran >>"$HOME/deferred-ran"; false'
OWN = 'echo ran >>"$HOME/own-ran"; false'


class DeferredToItsFixRun(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "acme")
        root = self.rig.git("rev-list", "--max-parents=0", "HEAD")[:12]
        Seat(self.home, SEAT, alive=False, cwd=self.rig.path, record={"repo": str(self.rig.path)})
        where = f"~/code/acme#{root}"
        self.home.write(f".agentkit/state/plan-{SEAT}.md",
                        f"- [ ] the mode is right · check: `{DEFERRED}` · {where} · deferred"
                        " · written 2026-11-06 09:00\n"
                        f"- [ ] the api retries · check: `{OWN}` · {where}"
                        " · written 2026-11-06 09:00\n")

    def fix_run(self, **state):
        """The seat's fix run for the deferred line, in its repository, as its record says."""
        self.home.write(".agentkit/runs/fix-the-mode/run.json", {
            "run_id": "fix-the-mode", "launched_session": SEAT, "repo": str(self.rig.path),
            "followup": {"run": "source", "text": "api.py:1 - mode is wrong", "place": "api.py:1",
                         "check": DEFERRED}, **state})

    def verified(self):
        """`ak plan` in the seat, then how many times each line's check has run."""
        done = self.home.ak("plan", env={"AGENTKIT_SESSION": SEAT})
        self.assertEqual(done.code, 0, done.out + done.err)
        return tuple(len(path.read_text().splitlines()) if path.exists() else 0
                     for path in (self.home.path / "deferred-ran", self.home.path / "own-ran"))

    def test_a_queued_fix_run_keeps_its_line_until_it_ends(self):
        self.fix_run(state="queued", slot_waiting=True, pid=None)
        self.assertEqual(self.verified(), (0, 1))
        self.fix_run(state="fail", merged=False, finished_at=1.0)
        self.assertEqual(self.verified(), (1, 2))

    def test_a_running_fix_run_keeps_its_line(self):
        self.fix_run(state="running", pid=None)
        self.assertEqual(self.verified(), (0, 1))

    def test_a_paused_fix_run_leaves_its_line_to_the_seat(self):
        # waiting for a login it may get hours later: a fix landing meanwhile ticks it here
        self.fix_run(state="waiting_login", waiting_for="claude")
        self.assertEqual(self.verified(), (1, 1))


if __name__ == "__main__":
    unittest.main()
