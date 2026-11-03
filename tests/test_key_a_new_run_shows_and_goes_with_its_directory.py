"""A new run shows at once and goes with its directory."""

import shutil
import time
import unittest

from test_key_runs_at_rest_cost_an_open_screen_little import (
    RUNS, SEATS, RestScreen, ended, going, row)


class RunsAtRestCostAnOpenScreenLittle(RestScreen):
    def test_3_a_new_run_shows_at_once_and_goes_with_its_directory(self):
        record = going(ended(RUNS, SEATS[2], time.time()))
        kept = self.home.write(f".agentkit/runs/{record['run_id']}/run.json", record)
        (self.home.path / ".agentkit/state/runs-moved").touch()
        self.menu.wait(row(SEATS[2], "● working"))
        shutil.rmtree(kept.parent)
        self.menu.wait(self.not_working)


if __name__ == "__main__":
    unittest.main()
