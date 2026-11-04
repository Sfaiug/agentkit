"""Retirement's answer key, proof boundary and tick's pass with a fake working seat."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, retire
from test_key_retire_line_waits_for_proof import (
    SWITCH, RetireLineWaitsForProof, RetirementPlan, retirement_check)


class TickPlansProvenSwitch(RetirementPlan):
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
        self.assertIn(f"`{retirement_check()}`", lines[0])


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
