"""A renamed seat shows its runs under its new name."""

import json
import unittest

from test_key_runs_at_rest_cost_an_open_screen_little import (
    LATE, SEATS, RestScreen, going, row)


class RunsAtRestCostAnOpenScreenLittle(RestScreen):
    def test_5_a_seat_renamed_shows_its_runs_under_its_new_name(self):
        self.home.write(self.runs[SEATS[1]],
                        going(json.loads(self.runs[SEATS[1]].read_text())))
        self.menu.wait(row(SEATS[1], "● working"), bound=LATE)
        done = self.home.ak("orch", "rename", SEATS[1], "acme-renamed")
        self.assertEqual(done.code, 0, done.err)
        self.menu.wait(row("acme-renamed", "● working"))


if __name__ == "__main__":
    unittest.main()
