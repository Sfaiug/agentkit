"""A model turn on a rented machine keeps the timeouts its commands declared: a command there that
prints nothing goes on past the silence limit while it is inside its `timeout N`, as one here
does; one with no bound is stopped at the limit.

Black-box, on the machine tests/test_key_a_turn_runs_on_a_machine.py runs turns on, whose
containers run outside the process tree of the ssh that started them, as a real machine's do. A
run's silence limit is the one its record holds when its loop starts: the executor's first two
turns, with the switch off, each end by a signal, which parks the run `interrupted`; its record
then gets a limit of three seconds, and `ak run resume` runs the third turn on the machine. That
turn streams one event, runs its command, and hands in blocked, which ends the run unreviewed.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

SILENCE_MINUTES = 0.05
# Its harness killed, and no conversation left for a resume: one to resume runs here.
KILLED = {"sh": "kill -TERM $PPID", "session": ""}
OUT = '"${AK_HAND_IN%/*}"'


def record(run):
    return json.loads((run / "run.json").read_text())


class ATurnOnAMachineKeepsItsDeclaredTimeout(unittest.TestCase):
    def parked(self, command):
        """(Home, run) of a run parked before its third turn, which runs `command` on the
        machine with a silence limit of three seconds."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        fakeadapter.install(home, claude=[KILLED, KILLED, {
            "sh": f'echo "${{container:-here}}" >{OUT}/where; echo {{}} >>{OUT}/events.jsonl; '
                  f"{command}",
            "final": "Blocked.", "hand_in": [["blocked", "the fixture needs the owner"]]}])
        machine = akmachine.install(home)
        home.fake("claude", "#!/bin/sh\necho 1.2.3\n")
        (machine / "home/.agentkit-helper/harness/claude/1.2.3").mkdir(parents=True)
        (machine / "home/.agentkit-helper/harness/claude/1.2.3/claude").touch(0o755)
        settings = {"suite_helper": "acme-linux", "turns_on_machines": False}
        akconfig.write(home, ["opus", "astra"], settings=settings)
        home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
        run = taskfile.only_run(home)
        state = record(run)
        self.assertEqual(state["state"], "interrupted", state)
        (run / "run.json").write_text(json.dumps({**state, "silence_minutes": SILENCE_MINUTES}))
        akconfig.write(home, ["opus", "astra"], settings={**settings, "turns_on_machines": True})
        return home, run

    def test_a_silent_command_under_a_declared_timeout_runs_to_its_end(self):
        home, run = self.parked("timeout 30 sleep 6")
        home.ak("run", "resume", run.name, timeout=300)
        self.assertEqual(record(run)["state"], "blocked", record(run))
        self.assertEqual([path.read_text() for path in run.rglob("where")], ["docker\n"])

    def test_a_silent_command_with_no_declared_bound_is_stopped_at_the_limit(self):
        home, run = self.parked("sleep 6")
        resumed = home.spawn("run", "resume", run.name)
        deadline = time.monotonic() + 120
        # stopped, the turn waits to be tried again
        while not record(run).get("transient_wait"):
            self.assertLess(time.monotonic(), deadline, "the turn was never stopped")
            self.assertIsNone(resumed.poll(), record(run))
            time.sleep(0.2)
        self.assertIn("emitted no event for 3s", (run / "log.txt").read_text())
        self.assertEqual([*run.rglob("where")], [])


if __name__ == "__main__":
    unittest.main()
