"""A delivered run's ending never waits for another's plan verification, and every delivery is
still checked by a verification begun after it.

The seat's `ak plan` verifies its plan, one line's check blocking until the test releases it.
Two runs of the seat merge meanwhile: each one's process ends within a bound, its review
follow-up handed on, and the blocking check never runs twice at once.  Released, the plan is
verified again for them: the line only the second merge proves is ticked on that merge.
Black-box: AK_BIN runs against Home, Rig, GitHub and Seat, with scripted harnesses from
fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

BOUND = 300     # one `ak run` of scripted turns, on a loaded host
CHECK = "test -f sturdy.txt"
OUTCOME = "Fix AGENTS.md:1 - flimsy widget - it breaks later"
REVIEW = {"final": "One more defect.", "hand_in": [
    ["follow-up", "AGENTS.md:1", "flimsy widget", "it breaks later", "--run", CHECK], ["done"]]}
# the follow-up's fix run, launched by the first merge, holds its turn till the Home ends: its
# own ending is no part of this test
HOLD = {"sh": "sleep 900"}
BOTH = "test -f first.txt && test -f second.txt"


def made(name):
    """An executor's turn that writes `name` and commits it."""
    return {"write": {name: "ok\n"}, "commit": f"add {name}", "final": f"## Summary\nwrote {name}",
            "hand_in": [["done"]]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EndingWaitsForNoVerification(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "app")
        GitHub(self.home).grant(self.rig.slug, "WRITE")
        akconfig.write(self.home, ["opus", "astra"])
        self.fakes = fakeadapter.install(self.home, claude=[made("first.txt"), HOLD, made("second.txt"), HOLD],
                                         codex=REVIEW)
        Seat(self.home, "acme", cwd=self.rig.path, record={"reviewers": ["astra"]})
        root = self.rig.git("rev-list", "--max-parents=0", "HEAD")[:12]
        # a check that records itself entering, and a second one entering while it checks
        self.marks = self.home.root
        block = self.marks / "block.sh"
        block.write_text(f"cd {shlex.quote(str(self.marks))}\n"
                         "mkdir checking 2>/dev/null || : >twice\n"
                         ": >blocked\n"
                         "while [ ! -e released ]; do sleep 0.1; done\n"
                         "rmdir checking\n"
                         "exit 1\n")
        self.home.write(".agentkit/state/plan-acme.md", "".join(
            f"- [ ] {what} · check: `{check}` · ~/code/app#{root} · written 2026-11-06 09:00\n"
            for what, check in (("a slow check passes", f"sh {shlex.quote(str(block))}"),
                                ("both files are in", BOTH))))

    def until(self, ready, why, bound=120):
        deadline = time.monotonic() + bound
        while not ready():
            self.assertLess(time.monotonic(), deadline, why)
            time.sleep(0.1)

    def plan(self):
        return (self.home.path / ".agentkit/state/plan-acme.md").read_text().splitlines()

    def deliver(self, title, name):
        """One run of the seat, writing `name`, to its process's end; its record."""
        task = taskfile.write(self.home, self.rig.path, title, done_when=(f"test -f {name}",))
        done = self.home.ak("run", str(task), env={"AGENTKIT_SESSION": "acme"}, timeout=BOUND)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = next(run for run in taskfile.runs(self.home)
                   if (run / "task.md").read_text().startswith(task.read_text()))
        state = json.loads((run / "run.json").read_text())
        self.assertTrue(state.get("merged"), state)
        self.assertEqual([entry.get("outcome") for entry in state.get("followup_plan") or []],
                         [OUTCOME], state)
        return state

    def test_runs_merged_while_the_plan_verifies_end_at_once_and_their_merges_are_checked(self):
        verifier = self.home.spawn("plan", env={"AGENTKIT_SESSION": "acme"})
        self.until(lambda: (self.marks / "blocked").exists() or verifier.poll() is not None,
                   "ak plan never began its check")
        self.assertTrue((self.marks / "blocked").exists(), self.home.log("spawn-1.err").read_text())
        self.deliver("Add first file", "first.txt")
        # the first merge's fix run takes the next turn, so the second run takes its own
        self.until(lambda: self.fakes["claude"].n >= 2, "the follow-up's fix run never began")
        self.deliver("Add second file", "second.txt")
        self.assertIsNone(verifier.poll(), "ak plan ended before its check was released")
        (self.marks / "released").write_text("")
        self.assertEqual(verifier.wait(BOUND), 0, self.home.log("spawn-1.err").read_text())
        merged = self.rig.head()[:12]
        self.until(lambda: any(line.startswith("- [x] both files are in ·") and f" · done {merged} " in line
                               for line in self.plan()),
                   f"the second merge was never checked: {self.plan()}")
        self.assertFalse((self.marks / "twice").exists(), "the blocking check ran twice at once")


if __name__ == "__main__":
    unittest.main()
