"""A run delivering a green landing verdict has the landing check's CPU weight: it asks for it on
its own unit before it waits for its delivery turn, and for a run's again where it rejoins.

Offline: the lander's acme sandbox (`test_lander.LanderFixture`), a fake cgroup membership
(AK_CGROUP_FILE) in the member's unit, and a systemctl first on PATH that records each argv.
"""

import json
import os
import shlex
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_lander import LanderFixture, land, record, run
from fixtures.akbin import LOG
from agentkit import deliver as delivery

UNIT = "agentkit-run-fix-api"
SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"


def weight(value):
    return ["--user", "set-property", "--runtime", f"{UNIT}.scope", f"CPUWeight={value}"]


class DeliveringRunHasTheLandingWeight(LanderFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.calls = self.root / "systemctl.log"
        self.bin = self.root / "fakebin"
        self.bin.mkdir()
        membership = self.root / "membership"
        membership.write_text(f"0::/{SERVICE}/agentkit.slice/agentkit-runs.slice/{UNIT}.scope\n")
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_CGROUP_FILE": str(membership), "PATH": f"{self.bin}:{os.environ['PATH']}"}))
        self.manager(0)
        self.lines = []

    def manager(self, code):
        script = self.bin / "systemctl"
        script.write_text(LOG.format(python=shlex.quote(sys.executable),
                                     log=shlex.quote(str(self.calls))) + f"exit {code}\n")
        script.chmod(0o755)

    def asked(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def green(self, scope=UNIT):
        member = self.member()
        with record.record(member) as state:
            state["scope"] = scope
        self.advance()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(member))
        return member

    def deliver(self, member):
        state = record.read_state(member)
        lp = SimpleNamespace(state=state, wt=self.repo, run_dir=member, base_sha=self.base,
                             target="main", log=self.lines.append,
                             write=lambda: record.save_state(member, state))
        run.git(self.repo, "checkout", state["branch"])

        def deliver():
            run.git(self.repo, "push", "origin", "HEAD:main")
            state.update(state="pass", merged=True)
            return True

        locking = delivery.merge_lock

        def merge_lock(*args):
            self.before_lock = self.asked()
            return locking(*args)

        with patch.object(delivery, "merge_lock", side_effect=merge_lock):
            return delivery.land_from_line(lp, "origin/main", deliver)

    def test_a_green_member_asks_for_the_checks_weight_before_the_lock_and_merges(self):
        member = self.green()
        self.assertTrue(self.deliver(member))
        self.assertEqual(self.before_lock, [weight(10000)])
        self.assertEqual(self.asked(), [weight(10000)])
        self.assertTrue(record.read_state(member)["merged"])

    def test_a_member_whose_target_moved_asks_for_a_runs_cpu_again_as_it_rejoins(self):
        member = self.green()
        self.advance(**{"moved.txt": "moved\n"})
        self.assertFalse(self.deliver(member))
        self.assertEqual(record.read_state(member)["state"], "waiting")
        self.assertEqual(self.asked(), [weight(10000), weight("idle")])

    def test_a_member_in_no_unit_of_its_own_asks_nothing(self):
        member = self.green(scope="none")
        self.assertTrue(self.deliver(member))
        self.assertEqual(self.asked(), [])

    def test_a_refusing_manager_costs_one_warn_line_and_the_delivery_merges(self):
        self.manager(1)
        member = self.green()
        self.assertTrue(self.deliver(member))
        self.assertTrue(record.read_state(member)["merged"])
        self.assertEqual(self.asked(), [weight(10000)])
        self.assertEqual(len([line for line in self.lines if line.startswith("WARN")]), 1,
                         self.lines)


if __name__ == "__main__":
    unittest.main()
