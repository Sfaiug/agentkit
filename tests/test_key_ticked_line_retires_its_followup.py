"""A plan line ticking ends the queued runs that only repeat its check: one in its repository
that never held a slot and whose follow-up check is the line's ends `stopped`, naming the line
and the commit, so its seat reads done; another check, or a run that started, is left alone;
and a line replaced while its check ran ends no run.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, on a project tests/fixtures/gitrig.py keeps, beside
run records written where it reads them, and this test fails against `/bin/false`.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

SEAT = "fix-api"
OTHER_SEAT = "acme-ui"
CHECK = "test -f feature.txt"
QUEUED = {"state": "queued", "slot_waiting": True, "pid": None}


class Ticked(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "acme")
        Seat(self.home, SEAT, alive=False, cwd=self.rig.path,
             record={"repo": str(self.rig.path)})

    def plan(self, *args):
        done = self.home.ak("plan", *args, env={"AGENTKIT_SESSION": SEAT})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def run_record(self, run_id, check, **state):
        self.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "launched_session": SEAT, "repo": str(self.rig.path),
            "followup": {"run": "source", "text": "api.py:1 - mode is wrong", "place": "api.py:1",
                         "check": check}, **state})
        return run_id

    def state(self, run_id):
        return json.loads((self.home.path / f".agentkit/runs/{run_id}/run.json").read_text())

    def why(self):
        """The seat's word, and the reason for it: a finished plan's last done line."""
        done = self.home.ak("orch", "why", SEAT)
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines()[:2]

    def test_the_line_ticking_ends_only_the_queued_run_repeating_its_check(self):
        self.plan("add", "Fix the mode", "--check", CHECK)
        repeat = self.run_record("repeat", CHECK + " ", **QUEUED)       # trimmed, it is the check
        # a queued launcher recovered before it ever held a slot never started either
        recovered = self.run_record("recovered", CHECK, **QUEUED, resume_from="interrupted")
        # requeued after it held a slot: started, so its next round hands in not-needed
        requeued = self.run_record("requeued", CHECK, **QUEUED, resume_from="running",
                                   slot_started_at=1.0, launched_session=OTHER_SEAT)
        # another seat's, so what is left open is no work of this seat's
        other = self.run_record("other", "test -f other.txt", **QUEUED,
                                launched_session=OTHER_SEAT)
        started = self.run_record("started", CHECK, state="running", slot_waiting=False, pid=None,
                                  launched_session=OTHER_SEAT)
        # its subject is not the line's words, so only the line can put them in an error
        commit = self.rig.commit({"feature.txt": "fixed\n"}, "land the feature")[:12]

        self.plan()

        for run_id in (repeat, recovered):
            ended = self.state(run_id)
            self.assertEqual(ended["state"], "stopped")
            self.assertIn("Fix the mode", ended["error"])
            self.assertIn(commit, ended["error"])
        self.assertEqual(self.state(requeued)["state"], "queued")
        self.assertEqual(self.state(other)["state"], "queued")
        self.assertEqual(self.state(started)["state"], "running")
        self.assertEqual(self.why(), [f"{SEAT}  done", "  reason:    Fix the mode"])

    def test_a_line_replaced_while_its_check_ran_ends_no_run(self):
        # the check passes once the work lands, and puts another check in the line's place
        again = shlex.join([AK, "plan", "check", "1", "test -f other.txt"])
        replace = self.home.write("replace.sh", f"AGENTKIT_SESSION={SEAT} {again}\n")
        check = f'test -f feature.txt && sh "$HOME/{replace.name}"'
        line = self.plan("add", "Fix the mode", "--check", check).strip()
        self.plan("add", "Fix the rest", "--check", "test -f rest.txt")
        queued = self.run_record("queued", check, **QUEUED)
        self.rig.commit({"feature.txt": "fixed\n"}, "land the feature")

        self.plan()

        stored = (self.home.path / f".agentkit/state/plan-{SEAT}.md").read_text().splitlines()
        self.assertIn(line.replace(check, "test -f other.txt"), stored)
        self.assertEqual(self.state(queued)["state"], "queued")


if __name__ == "__main__":
    unittest.main()
