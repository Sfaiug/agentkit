"""`ak plan` takes an open deferred line out of its seat's plan without running its check, even
while its fix run is still going and when no other line can be checked, and leaves a ticked
deferred line and the seat's own lines as written.

Review follow-ups were once written into their seat's plan marked deferred, as a fix run's.  On
18 Nov 2026 such lines, their fix runs failed, blocked or stopped, held a seat open with nothing
of its own to do; the fix run's record is where a follow-up lives.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py in a seat's environment, over
projects whose origin is a bare repository on disk, and this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

SEAT = "fix-api"
PLAN = f".agentkit/state/plan-{SEAT}.md"
# passes on the default branch, so a line kept and checked would tick, and leaves a trace
DEFERRED = 'echo ran >>"$HOME/deferred-ran"'


def plan(where):
    """On project `where`: an open deferred line, a ticked deferred line and an open line of the
    seat's own."""
    return (f"- [ ] the mode is right · check: `{DEFERRED}` · {where} · deferred · "
            "written 2026-11-18 09:00",
            f"- [x] the api retries · check: `test -f retry.txt` · {where} · deferred · "
            "written 2026-11-18 09:05 · done 0123456789ab add retries",
            f"- [ ] the parser reads tabs · check: `false` · {where} · written 2026-11-18 09:10")


class ADeferredLineLeavesItsPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rigs = {name: Rig(cls.home, name) for name in ("acme", "widgets")}
        cls.where = {name: f"~/code/{name}#{rig.git('rev-list', '--max-parents=0', 'HEAD')[:12]}"
                     for name, rig in rigs.items()}
        # its origin gone: no check of that project can run
        rigs["widgets"].git("remote", "set-url", "origin", str(cls.home.root / "gone.git"))
        Seat(cls.home, SEAT, alive=False, cwd=rigs["acme"].path,
             record={"repo": str(rigs["acme"].path)})
        cls.home.write(".agentkit/runs/20261118-0900-fix-the-mode/run.json", {
            "run_id": "20261118-0900-fix-the-mode", "launched_session": SEAT, "state": "running",
            "repo": str(rigs["acme"].path),
            "followup": {"run": "source", "text": "api.py:1 - mode is wrong", "check": DEFERRED}})

    def listed(self, *lines, code=0):
        """`ak plan` in the seat over a plan of those lines, exiting `code`: the lines it listed,
        in order, and the plan's file after."""
        self.home.write(PLAN, "".join(f"{line}\n" for line in lines))
        done = self.home.ak("plan", env={"AGENTKIT_SESSION": SEAT, "COLUMNS": "250"})
        self.assertEqual(done.code, code, done.err)
        self.assertFalse((self.home.path / "deferred-ran").exists(), "a deferred check ran")
        rows = [re.fullmatch(r" *(\d+)  (- \[.\] .*)", row) for row in done.out.splitlines()]
        self.assertTrue(all(rows), done.out)
        self.assertEqual([int(row[1]) for row in rows], list(range(1, len(rows) + 1)), done.out)
        return [row[2] for row in rows], (self.home.path / PLAN).read_text().splitlines()

    def test_the_open_deferred_line_leaves_and_the_others_stand(self):
        deferred, ticked, own = plan(self.where["acme"])
        shown, stored = self.listed(deferred, ticked, own)
        self.assertEqual(stored, [ticked, own])
        self.assertEqual(shown, stored)
        self.assertEqual([line for line in shown if line.startswith("- [ ] ")], [own])

    def test_a_plan_whose_only_open_line_was_deferred_lists_no_open_line(self):
        shown, stored = self.listed("# fix-api", plan(self.where["acme"])[0])
        self.assertEqual(stored, ["# fix-api"])
        self.assertEqual(shown, [])

    def test_a_project_that_cannot_be_checked_keeps_no_deferred_line(self):
        deferred, ticked, own = plan(self.where["widgets"])
        _, stored = self.listed(deferred, ticked, own, code=2)
        self.assertEqual(stored, [ticked, own])


if __name__ == "__main__":
    unittest.main()
