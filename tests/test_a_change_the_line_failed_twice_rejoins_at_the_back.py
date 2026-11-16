"""A change the line's check failed twice rejoins at the back; every other rejoin keeps its place.

In-process, as tests/test_lander_wakes.py is: a run's own side of its line has no black-box
fixture.  The lander's verdicts are written as it writes them, the run's repair and re-review
pass, and the clock is injected.
"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, deliver, land, record, roundloop
from fixtures.sandbox import Sandbox


class FailedTwiceRejoinsAtTheBack(Sandbox):
    def setUp(self):
        super().setUp()
        self.turn = config.RUNS / ".merge-acme.lock"
        self.clock = [100]
        self.stack.enter_context(patch.object(land, "start_line"))
        self.stack.enter_context(patch.object(deliver, "turn_path", return_value=self.turn))
        self.stack.enter_context(patch.object(deliver.time, "time", side_effect=lambda: self.clock[0]))
        self.stack.enter_context(patch.object(roundloop, "integrate", return_value=True))
        self.stack.enter_context(patch.object(roundloop, "fix_final_check", return_value=True))
        for name, joined in (("fix-api", 10), ("fix-docs", 20), ("fix-ui", 30)):
            self.join(name, joined)
        directory = config.RUNS / "fix-api"
        self.lp = SimpleNamespace(run_dir=directory, state=record.read_state(directory),
                                  log=lambda _line: None)
        self.lp.write = lambda: record.save_state(directory, self.lp.state)

    def join(self, name, joined):
        directory = config.RUNS / name
        directory.mkdir()
        record.save_state(directory, {"run_id": name, "state": "waiting",
                                      "waiting_on": {"line": self.turn.name, "joined": joined}})

    def line(self):
        return [directory.name for directory, _ in land.line(self.turn)]

    def sent_back(self, **failure):
        """The line's check fails fix-api, and its repair passes review."""
        log = self.lp.run_dir / "lander.log"
        log.write_text("FAIL test_widget\n")
        self.lp.state["waiting_on"] = {**self.lp.state["waiting_on"], "fix": {
            "line": "FAIL test_widget", "log": str(log), **failure}}
        self.lp.write()
        self.assertFalse(deliver.land_from_line(self.lp, "origin/main",
                                                lambda: self.fail("a red member delivered")))

    def test_the_second_red_sends_it_behind_those_that_waited(self):
        self.sent_back()
        self.assertEqual(self.line(), ["fix-api", "fix-docs", "fix-ui"])
        self.sent_back()
        self.assertEqual(self.line(), ["fix-docs", "fix-ui", "fix-api"])
        self.clock[0] = 150
        self.join("fix-cli", 150)
        self.clock[0] = 200
        # a conflict with the target is the world moving, not the work failing its check
        self.sent_back(conflict=True)
        self.assertEqual(self.line(), ["fix-docs", "fix-ui", "fix-api", "fix-cli"])
        # green on the line, it meets a moved target (`deliver.do_merge`)
        self.lp.state["waiting_on"] = {**self.lp.state["waiting_on"], "land": "tree"}
        self.assertFalse(deliver.rejoin_line(self.lp, "origin/main", "the PR's target moved"))
        self.assertEqual(self.line(), ["fix-docs", "fix-ui", "fix-api", "fix-cli"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
