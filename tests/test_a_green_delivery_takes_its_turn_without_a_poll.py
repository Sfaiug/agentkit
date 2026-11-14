"""A green delivery takes its turn as soon as the one ahead has left the line: each delivery, as
it ends, however it ends, wakes the next.

Offline: real Git and checks, sandbox records, fake processes and wakes, an injected clock.
"""

import fcntl
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_lander import LanderFixture, land, record, run, gate
from fixtures.clock import Clock
from agentkit import config, deliver as delivery, roundloop


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

    def delivering(self, directory, said):
        """`directory`'s run as it delivers, its branch checked out."""
        state = record.read_state(directory)
        state.update(state="running")
        lp = SimpleNamespace(state=state, wt=self.repo, run_dir=directory, base_sha=self.base,
                             target="main", log=said.append)
        lp.write = lambda: record.save_state(lp.run_dir, lp.state)
        lp.write()
        run.git(self.repo, "checkout", state["branch"])
        return lp

    def test_each_delivery_as_it_ends_wakes_the_next(self):
        members = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                   for n in range(1, 4)]
        self.advance()
        land.check_line(self.turn)
        said = []
        for n, ending in enumerate(("merged", "red"), 1):
            lp = self.delivering(members[n - 1], said)

            def deliver(lp=lp, ending=ending):
                if ending == "red":
                    lp.state["waiting_on"] = {**lp.state["waiting_on"], "fix": {"line": "red", "log": "x"}}
                    return False
                run.git(self.repo, "push", "origin", "HEAD:main")
                lp.state.update(state="pass", merged=True)
                return True

            self.assertEqual(delivery.land_from_line(lp, "origin/main", deliver), ending == "merged")
            self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                             [m.name for m in members[:n + 1]])
            self.assertEqual(said[-1], f"{members[n].name} delivers next in {self.turn.name}, "
                                       f"{2 - n} waiting behind it")

    def assert_hands_on(self, ending):
        """The head's delivery, ending unmerged as `ending`, wakes the one behind it."""
        first, second = [self.member(f"member-{n}", joined=n, **{f"member-{n}.txt": f"{n}\n"})
                         for n in (1, 2)]
        self.advance()
        land.check_line(self.turn)
        said = []
        lp = self.delivering(first, said)
        self.wake.reset_mock()

        def deliver():
            if ending == "raised":
                raise config.Error("gh: acme/widget unreachable")
            return roundloop.note(lp, "gh pr merge failed for acme/widget", failed=True)

        if ending == "raised":
            with self.assertRaises(config.Error):
                delivery.land_from_line(lp, "origin/main", deliver)
        else:
            self.assertFalse(delivery.land_from_line(lp, "origin/main", deliver))
        # its record still reads as delivering, till its run writes how it ended
        self.assertEqual([directory for directory, _ in land.line(self.turn)], [first, second])
        self.assertEqual([call.args[0] for call in self.wake.call_args_list], [second.name])
        self.assertEqual(said[-1], f"{second.name} delivers next in {self.turn.name}, "
                                   "0 waiting behind it")

    def test_a_delivery_that_fails_wakes_the_next_too(self):
        self.assert_hands_on("failed")

    def test_a_delivery_that_raises_wakes_the_next_too(self):
        self.assert_hands_on("raised")


if __name__ == "__main__":
    unittest.main()
