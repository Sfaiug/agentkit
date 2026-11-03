"""A seat holds no retirement line before its switch is proven; ak plans it then.

`AK_BIN plan add` runs in a throwaway HOME with a local origin and a deployed switch list,
as retirement reads it. The tick's pass is also exercised with a fake working seat.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, retire
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

SWITCH = "analytics_events"


class RetireLineWaitsForProof(unittest.TestCase):
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
                            "--check", command or retire.check({"id": SWITCH}, True),
                            env={"AGENTKIT_SESSION": "fix-api"})

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
        self.assertIn(f"`{retire.check({'id': SWITCH}, True)}`", done.out)

    def test_a_quoted_switch_id_is_also_refused(self):
        row = self.switch(3, id="analytics events")
        done = self.add(retire.check(row, True))
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertFalse(self.plan.exists())

    def test_other_checks_are_unchanged(self):
        self.switch(3)
        for command in ("test -f retired.txt", retire.check({"id": SWITCH}, True) + " && false"):
            with self.subTest(command=command):
                done = self.add(command)
                self.assertEqual(done.code, 0, done.err)
                self.assertIn(f"`{command}`", self.plan.read_text())
        self.switch(3, everyone_since=None)
        done = self.add(retire.check({"id": SWITCH}, False))
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

    def test_the_tick_still_plans_a_proven_switch_in_a_working_seat(self):
        older = self.switch(20)
        fresh = {**self.switch(3), "id": "fresh_search"}
        self.list.write_text(json.dumps([older, fresh]))
        done = self.home.run(sys.executable, "-c", f"""
import sys
sys.path.insert(0, {str(REPO)!r})
from unittest.mock import patch
from agentkit import orch, retire, watch
watch.seat_write('fix-api', word='working')
with patch.object(orch, 'sessions', return_value=[{{'name': 'fix-api', 'created': 1}}]):
    retire.hand(print)
""")
        self.assertEqual(done.code, 0, done.out + done.err)
        lines = self.plan.read_text().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("acme's switch analytics_events is out of the code", lines[0])
        self.assertIn(f"`{retire.check(older, True)}`", lines[0])


class ProofBoundary(unittest.TestCase):
    def test_the_proven_check_waits_until_exactly_fourteen_days(self):
        row = {"id": SWITCH, "everyone": True, "everyone_since": "2026-10-20T06:00:00-06:00"}
        proof = datetime(2026, 11, 3, 12, tzinfo=timezone.utc).timestamp()
        command = retire.check(row, True)
        with patch.object(menu, "features_run", return_value=([row], "")):
            for now in (proof - 1, proof, proof + 1):
                with self.subTest(now=now), patch.object(retire.time, "time", return_value=now):
                    if now < proof:
                        with self.assertRaisesRegex(config.Error, "2026-11-03"):
                            retire.vet_check(Path("acme"), command)
                    else:
                        retire.vet_check(Path("acme"), command)


if __name__ == "__main__":
    unittest.main()
