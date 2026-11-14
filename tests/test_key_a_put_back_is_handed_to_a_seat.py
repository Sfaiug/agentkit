"""A move put back is handed to a seat, and that seat's next agentkit run goes first in line.

`ak back` puts the last move of ~/agentkit back by hand on the Home tests/fixtures/akinstall.py
makes, with the seat that merged into agentkit at its prompt.  The next tick types it one line
naming the commit put back, and the one ~/agentkit went back to; three more ticks, with a later
release on origin meanwhile, type no other line naming it.  With two runs at a time
(`max_runs`), each slot taken by a run of that seat whose executor turn holds until the test
lets it go, so the seat may have two waiting (`gate.seat_full`), an agentkit run it launched
before it was told waits queued, and the one it launches after starts at once, whatever
~/agentkit moved to since.  On a Home with no seat, `ak back` and the ticks after it exit 0.
Black-box, the whole file in one box (`rerun_boxed`), as
tests/test_key_ticks_that_stop_after_a_move_put_it_back.py is; runs take the harnesses
tests/fixtures/fakeadapter.py scripts, in a clone of their own whose origin reads acme/agentkit,
and the slot poll and host readings are ak's own knobs (AK_SLOT_POLL, AK_HOST_READINGS), so only
the count holds a run.
"""

import json
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.akseat import PLAN_LINE

READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}
WAITING = ("queued", "running")
AGENTS = "---\ntests: true\nhealth: none\nusers: none\n---\n"


def wait(test, what, bound=180):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class APutBackIsHandedToASeat(unittest.TestCase):
    def moved(self):
        """A Home whose tick moved ~/agentkit one commit on: the commit before and the one moved
        to."""
        self.home = home = self.enterContext(Home())
        del home.env["AK_MAX_RUNS"]
        home.env.update(AK_SLOT_POLL="0.5", AK_HOST_READINGS=json.dumps(READINGS))
        akconfig.write(home, ["opus", "astra"], settings={"max_runs": 2})
        self.install = Install(home)
        before, after = self.install.head(), self.install.advance()
        self.tick()
        self.assertEqual(self.install.head(), after)
        return before, after

    def tick(self):
        done = self.home.run(self.install.ak, "watch", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)

    def back(self):
        done = self.home.run(self.install.ak, "back", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)

    def project(self):
        """A clone whose origin, a bare repository of its own, reads as acme/agentkit."""
        bare = self.home.root / "fork" / "acme" / "agentkit.git"
        path = self.home.path / "code" / "agentkit"
        for where, *args in ((self.home.root, "init", "-q", "--bare", "-b", "main", str(bare)),
                             (self.home.root, "clone", "-q", str(bare), str(path))):
            self.git(where, *args)
        (path / "AGENTS.md").write_text(AGENTS)
        for args in (("add", "-A"), ("commit", "-q", "-m", "init"),
                     ("push", "-q", "origin", "main")):
            self.git(path, *args)
        return path

    def git(self, where, *args):
        done = self.home.run("git", "-C", str(where), *args)
        self.assertEqual(done.code, 0, done.err)

    def launch(self, project, title, seat=None):
        """A run of a task in `project`, launched from `seat` or from none; its directory."""
        known = set(taskfile.runs(self.home))
        # checking nothing, so no two read as one change under way
        task = taskfile.write(self.home, project, title, done_when=("true",))
        done = self.home.ak("run", str(task), "--no-merge", "--bg",
                            env={"AGENTKIT_SESSION": seat} if seat else None)
        self.assertEqual(done.code, 0, done.out + done.err)
        new, = set(taskfile.runs(self.home)) - known
        return new

    @staticmethod
    def state(run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_the_seat_is_told_once_and_its_next_agentkit_run_starts_first(self):
        before, after = self.moved()
        seat = self.install.seat()
        self.home.write(f".agentkit/state/plan-{seat.name}.md", PLAN_LINE + "\n")
        fakes = fakeadapter.install(self.home, claude="work", codex="pass")
        release = fakes["claude"].dir / "release"
        # bounded, so a turn the test never let go cannot outlive it
        released = f"[ -f {shlex.quote(str(release))} ]"
        hold = {**fakeadapter.WORK,
                "sh": f"for i in $(seq 9000); do {released} && break; sleep 0.1; done"}
        fakes["claude"].behave(hold, hold, "work")
        project = self.project()
        runs = []
        self.addCleanup(wait, lambda: all(self.state(run).get("state") not in WAITING
                                          for run in runs), "every run's end", bound=600)
        self.addCleanup(release.touch)
        for slot in (1, 2):
            runs.append(self.launch(project, f"Hold slot {slot}", seat.name))
            wait(lambda: fakes["claude"].n == slot, f"held run {slot}'s executor turn")
        runs.append(self.launch(project, "Fix it early", seat.name))
        earlier = runs[-1]
        wait(lambda: self.state(earlier).get("slot_wait_kind") == "count",
             "the earlier run queued on the count")

        self.back()
        self.tick()
        # the seat's own merged run, which ended within the hour, is handed back to it too
        def told():
            return [line for line in seat.lines() if after[:12] in line]
        wait(told, "the put-back's line")
        line, = told()
        self.assertIn(before[:12], line)
        self.install.advance()
        for _ in range(3):
            self.tick()
        self.assertEqual(told(), [line])

        runs.append(self.launch(project, "Fix it", seat.name))
        fix = runs[-1]
        wait(lambda: self.state(fix).get("state") not in WAITING, "the fix's end")
        self.assertEqual(self.state(fix).get("verdict"), "PASS")
        self.assertEqual(self.state(earlier).get("state"), "queued")

    def test_with_no_seat_it_puts_back_and_ticks_as_before(self):
        before, _ = self.moved()
        self.back()
        self.assertEqual(self.install.head(), before)
        for _ in range(2):
            self.tick()


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
