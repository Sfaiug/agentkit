"""A run at rest that changes still shows on an open screen."""

import json
import unittest

from test_key_runs_at_rest_cost_an_open_screen_little import (
    LATE, SEATS, RestScreen, going, row)


class RunsAtRestCostAnOpenScreenLittle(RestScreen):
    def test_2_a_run_at_rest_that_changes_still_shows(self):
        for seat in SEATS[:2]:                    # past no mark: the run's writer told nobody
            self.home.write(self.runs[seat], going(json.loads(self.runs[seat].read_text())))
        for seat in SEATS[:2]:
            self.menu.wait(row(seat, "● working"), bound=LATE)


if __name__ == "__main__":
    unittest.main()
