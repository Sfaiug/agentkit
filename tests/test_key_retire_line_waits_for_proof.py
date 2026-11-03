"""A seat holds no retirement line before its switch is proven; ak plans it then.

Black-box: `AK_BIN plan add` runs in a throwaway HOME with a local origin and a deployed
switch list, as retirement reads it. Nothing here imports agentkit.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

SWITCH = "analytics_events"


def retirement_check(switch=SWITCH, proven=True):
    """The check in retirement plan lines written by Python ak."""
    return (f"python3 -c \"import sys; sys.path.insert(0, {str(REPO)!r}); "
            "from agentkit import retire; retire.check_main()\" "
            f"{shlex.quote(str(switch))} {'proven' if proven else 'unproven'}")


class RetirementPlan(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.list = self.home.root / "features.json"
        tool = self.home.fake("features", f"#!/bin/sh\ncat {shlex.quote(str(self.list))}\n")
        self.rig = Rig(self.home, "acme", files={
            "AGENTS.md": f"---\nfeatures: {tool}\n---\n# acme\n"})
        Seat(self.home, "fix-api", cwd=self.rig.path, record={"repo": str(self.rig.path)},
             alive=False)
        self.plan = self.home.path / ".agentkit/state/plan-fix-api.md"

    def switch(self, days, **fields):
        at = datetime.now(timezone.utc) - timedelta(days=days)
        row = {"id": SWITCH, "everyone": True, "everyone_since": at.isoformat(), **fields}
        self.list.write_text(json.dumps([row]))
        return row

    def add(self, command=None):
        return self.home.ak("plan", "add", "acme's analytics switch is out of the code",
                            "--check", command or retirement_check(),
                            env={"AGENTKIT_SESSION": "fix-api"})


class RetireLineWaitsForProof(RetirementPlan):
    def test_three_days_is_refused_with_its_proof_day_and_the_plan_unchanged(self):
        row = self.switch(3)
        day = (datetime.fromisoformat(row["everyone_since"]) + timedelta(days=14)).date()
        for before in (None, "- [x] the setup is done\n"):
            with self.subTest(before=before):
                if before is not None:
                    self.plan.write_text(before)
                done = self.add()
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertEqual(done.out, "")
                self.assertIn(str(day), done.err)
                self.assertIn("ak plans this line itself into a seat at work", done.err)
                self.assertIn("once it is proven", done.err)
                self.assertIn("the seat holds no line for it before then", done.err)
                self.assertEqual(self.plan.read_text() if self.plan.exists() else None, before)

    def test_twenty_days_can_be_planned(self):
        self.switch(20)
        done = self.add()
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.plan.read_text(), done.out)
        self.assertIn(f"`{retirement_check()}`", done.out)

    def test_a_quoted_switch_id_is_also_refused(self):
        row = self.switch(3, id="analytics events")
        done = self.add(retirement_check(row["id"]))
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertFalse(self.plan.exists())

    def test_other_checks_are_unchanged(self):
        self.switch(3)
        for command in ("test -f retired.txt", retirement_check() + " && false"):
            with self.subTest(command=command):
                done = self.add(command)
                self.assertEqual(done.code, 0, done.err)
                self.assertIn(f"`{command}`", self.plan.read_text())
        self.switch(3, everyone_since=None)
        done = self.add(retirement_check(proven=False))
        self.assertEqual(done.code, 0, done.err)

    def test_a_row_off_for_everyone_or_without_a_readable_date_refuses_nothing(self):
        for fields in ({"everyone": False}, {"everyone_since": None},
                       {"everyone_since": "not a date"}):
            with self.subTest(fields=fields):
                self.switch(3, **fields)
                done = self.add()
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(self.plan.read_text(), done.out)

    def test_an_unreadable_list_refuses_nothing(self):
        for answer in ('{"error": "offline"}', "not json", None):
            with self.subTest(answer=answer):
                if answer is None:
                    self.list.unlink()
                else:
                    self.list.write_text(answer)
                done = self.add()
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(self.plan.read_text(), done.out)


if __name__ == "__main__":
    unittest.main()
