"""A resume of a run answers its job's waiting line: no seat is typed it, no owner carded it.

A job ends at a failed task while the seat that launched it, and waits on it, is mid-turn, so
the job's line waits on its record for the seat's next prompt.  The seat resumes that run before
the prompt comes, as it does after reading `ak run status`; the resumed run hands back its own
ending, and the seat's wait is over without a line of its own.  A line that tells of several
tasks stays until each of their runs is resumed, and one nobody answered is typed once, as ever.
Black-box through AK_BIN: fake adapters and GitHub in acme/widget, and the seat that launched
the job.
"""

import json
import os
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable, owner, rerun_boxed
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


def wait_for(read, bound=180):
    deadline = time.monotonic() + bound
    while not (seen := read()):
        if time.monotonic() > deadline:
            raise AssertionError("the job did not reach its expected state")
        time.sleep(.1)
    return seen


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AResumeAnswersItsJobsLine(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        self.rig = Rig(home, "widget")
        GitHub(home)
        # mid-turn throughout: the job's line has to wait on its record for the next prompt
        self.seat = Seat(home, "acme", cwd=self.rig.path, planned=True,
                         screen="claude-working-pane.txt",
                         record={"workers": ["opus"], "reviewers": ["astra"]})
        # each review finds the fixture's defect in the task's one round; each turn holds
        # until the seat waits on the job
        self.fakes = fakeadapter.install(home, claude="work", codex="fail")
        self.waited = self.fakes["claude"].dir / "waited"
        self.fakes["claude"].behave({**fakeadapter.WORK, "sh": (
            f"for i in $(seq 1200); do [ -f {shlex.quote(str(self.waited))} ] && break; "
            "sleep .1; done")})

    def launch(self, *flags, names="ab"):
        """The seat launches the tasks as a job and waits on it, which then fails."""
        tasks = [taskfile.write(self.home, self.rig.path, f"Add {name}", name=name,
                                front={"rounds": 1}) for name in names]
        done = self.home.ak("run", *map(str, tasks), *flags, "--bg",
                            env={"AGENTKIT_SESSION": self.seat.name})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.directory, = (self.home.path / ".agentkit/jobs").iterdir()
        wait_for(lambda: self.fakes["claude"].n)
        done = self.home.ak("wait", self.directory.name, env={"AGENTKIT_SESSION": self.seat.name})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.waited.touch()
        wait_for(lambda: self.job().get("finished_at") and self.job().get("handback_pending"))

    def job(self):
        return json.loads((self.directory / "job.json").read_text())

    def wait(self):
        return json.loads((self.home.path / f".agentkit/state/seat-{self.seat.name}.json")
                          .read_text())["wait"]

    def run_of(self, name):
        return next(task["run_id"] for task in self.job()["tasks"]
                    if task["name"] == f"{name}.md")

    def resume(self, name):
        """The seat resumes the task's failed run, which fails again on its own: no run of it
        is left going, which a tick would take for one it has to recover."""
        run = self.home.path / ".agentkit/runs" / self.run_of(name) / "run.json"
        ended = json.loads(run.read_text())["finished_at"]
        done = self.home.ak("run", "resume", self.run_of(name), "--rounds", "2", "--bg",
                            env={"AGENTKIT_SESSION": self.seat.name})
        self.assertEqual(done.code, 0, done.out + done.err)
        wait_for(lambda: json.loads(run.read_text()).get("finished_at") not in (None, ended))

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def notices(self):
        """The job's lines the seat was told, its wait's among them, each up to its result's
        path."""
        return [line.split(". Result: ")[0] for line in self.seat.lines()
                if line.startswith(f"job {self.directory.name}")]

    def test_a_resumed_run_is_not_told_again_at_the_prompt(self):
        self.launch("--in-order")
        self.resume("a")
        self.assertNotIn("handback_pending", self.job())
        self.seat.show("claude-prompt-pane.txt")
        self.tick()
        self.tick()
        self.assertEqual(self.notices(), [])
        self.assertTrue(self.wait().get("told"))
        # its own ending, past the job's, is the run's to hand back, once
        own = [line for line in self.seat.lines()
               if line.startswith(f"run {self.run_of('a')} FAIL (2 of 2): ")]
        self.assertEqual(len(own), 1, self.seat.lines())

    def test_a_resumed_run_is_carded_to_nobody_once_its_seat_is_gone(self):
        self.launch("--in-order")
        self.resume("a")
        done = self.home.ak("orch", "stop", self.seat.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.tick()
        self.assertEqual([key for key in ("handback_pending", "card_pending") if key in self.job()],
                         [])
        self.assertNotEqual((self.job().get("card_sent") or {}).get("kind"), "needs")
        self.assertTrue(self.wait().get("told"))

    def test_a_line_nobody_answered_is_typed_once_at_the_next_prompt(self):
        self.launch("--in-order")
        self.seat.show("claude-prompt-pane.txt")
        self.tick()
        self.seat.wait_lines(1)
        self.tick()
        self.assertEqual(self.notices(), [f"job {self.directory.name}: a.md: FAIL after 1 rounds: "
                                          "needs you; not started: b.md"])
        self.assertNotIn("handback_pending", self.job())
        self.assertTrue(self.wait().get("told"))

    def test_a_line_telling_of_two_failed_runs_waits_for_both_resumes(self):
        # two held slots give this seat room to launch both tasks at once
        for name in ("api", "docs"):
            run_id = f"20261104-0900-fix-{name}"
            self.home.write(f".agentkit/runs/{run_id}/run.json", {
                "run_id": run_id, "launched_session": self.seat.name, "state": "running",
                "slot_started_at": time.time(), "slot_waiting": False, **owner(os.getpid())})
        self.launch()
        self.assertEqual([task["state"] for task in self.job()["tasks"]], ["failed", "failed"])
        self.resume("a")
        self.assertTrue(self.job().get("handback_pending"))
        self.resume("b")
        self.assertNotIn("handback_pending", self.job())
        self.seat.show("claude-prompt-pane.txt")
        self.tick()
        self.assertEqual(self.notices(), [])
        self.assertTrue(self.wait().get("told"))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
