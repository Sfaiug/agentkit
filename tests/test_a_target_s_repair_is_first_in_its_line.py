"""A target's repair is first in its line, behind its green deliveries only.

In-process on `land.line`, as tests/test_a_change_the_line_failed_twice_rejoins_at_the_back.py
is: the records as `handback.start_followups` writes a repair's, and the line as read.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, land, record
from fixtures.sandbox import Sandbox


class RepairIsFirstInItsLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.turn = config.RUNS / ".merge-acme.lock"
        for name, joined in (("fix-api", 10), ("fix-docs", 20), ("fix-ui", 30)):
            self.join(name, joined)
        self.join("repair-main", 40, repair={"target": "main", "command": "python3 tests/test_widget.py"})

    def join(self, name, joined, **fields):
        directory = config.RUNS / name
        directory.mkdir()
        record.save_state(directory, {"run_id": name, "state": "waiting", **fields,
                                      "waiting_on": {"line": self.turn.name, "joined": joined}})

    def line(self):
        return [directory.name for directory, _ in land.line(self.turn)]

    def test_the_repair_that_joined_last_is_first(self):
        self.assertEqual(self.line(), ["repair-main", "fix-api", "fix-docs", "fix-ui"])

    def test_a_green_delivery_stays_ahead_of_it(self):
        with record.record(config.RUNS / "fix-ui") as state:
            state["waiting_on"] = {**state["waiting_on"], "land": "tree"}
        self.assertEqual(self.line(), ["fix-ui", "repair-main", "fix-api", "fix-docs"])

    def test_two_repairs_keep_their_join_order(self):
        self.join("repair-flaky", 50, repair={"target": "main", "command": "tests/test_clock.py",
                                              "flaky": 45})
        self.assertEqual(self.line(), ["repair-main", "repair-flaky", "fix-api", "fix-docs", "fix-ui"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
