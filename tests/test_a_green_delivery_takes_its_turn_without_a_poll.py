"""A green delivery takes its turn as soon as the one ahead has left the line.

Offline: real Git and checks, sandbox records, fake processes and wakes, an injected clock.
"""

import fcntl
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_lander import LanderFixture, land, record, run, gate
from fixtures.clock import Clock
from agentkit import deliver as delivery


class GreenDeliveryTurn(LanderFixture, unittest.TestCase):
    def test_the_first_two_ask_for_the_lock_and_neither_sleeps_a_poll(self):
        members = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                   for n in range(1, 5)]
        self.advance()
        land.check_line(self.turn)
        loops = {}
        for directory in members:
            state = record.read_state(directory)
            state.update(state="running")
            lp = SimpleNamespace(state=state, wt=self.repo, run_dir=directory,
                                 base_sha=self.base, target="main", log=lambda _: None)
            lp.write = lambda lp=lp: record.save_state(lp.run_dir, lp.state)
            lp.write()
            loops[directory] = lp
        asking = members[::-1]      # the last asks first, the first last, each while the next sleeps
        asked, holders, sleeps, merged = [], [], [], []
        flock = fcntl.flock

        def place(directory):
            return [d for d, _ in land.line(self.turn)].index(directory)

        def lock(file, operation):
            flock(file, operation)
            if getattr(file, "name", None) == str(self.turn) and operation & fcntl.LOCK_EX:
                holders.append((asked[-1].name, place(asked[-1])))

        def sleep(seconds):
            sleeper = asked[-1]
            sleeps.append((sleeper.name, place(sleeper), seconds))
            if asking:
                attempt(asking.pop(0))
            run.git(self.repo, "checkout", loops[sleeper].state["branch"])

        def attempt(directory):
            asked.append(directory)
            lp = loops[directory]
            run.git(self.repo, "checkout", lp.state["branch"])

            def deliver():
                run.git(self.repo, "push", "origin", "HEAD:main")
                lp.state.update(state="pass", merged=True)
                merged.append(directory)
                return True

            self.assertTrue(delivery.land_from_line(lp, "origin/main", deliver))
            asked.pop()

        with patch.object(gate, "SLOT_POLL", 30), patch.object(delivery, "time", Clock(sleep)), \
                patch.object(delivery.fcntl, "flock", side_effect=lock):
            attempt(asking.pop(0))
        self.assertEqual(merged, members)
        # further back, five seconds for each member ahead; the second asks again after a second
        self.assertEqual(sleeps, [("member-4", 3, 15), ("member-3", 2, 10), ("member-2", 1, 1)])
        self.assertEqual(holders, [("member-2", 1), ("member-1", 0), ("member-2", 0),
                                   ("member-3", 0), ("member-4", 0)])
        self.assertEqual(run.git(self.repo, "rev-parse", "origin/main^{tree}"),
                         loops[members[-1]].state["final_check"]["tested"])
        self.assertEqual(land.line(self.turn), [])
        for directory in members:
            self.assertNotIn("delivery_wait", record.read_state(directory))


if __name__ == "__main__":
    unittest.main()
