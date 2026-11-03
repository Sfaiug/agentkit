"""A moved symlink shows by a full read, and a changed record at once."""

import time
import unittest

from test_key_runs_at_rest_cost_an_open_screen_little import (
    LATE, RUNS, SEATS, RestScreen, ended, going, row)


class RunsAtRestCostAnOpenScreenLittle(RestScreen):
    def test_4_a_symlink_that_moved_shows_by_a_full_read_and_a_changed_record_at_once(self):
        code, sandbox = self.home.path / "code", self.home.path / ".agentkit/tmp/smoke-acme"
        link = code / "acme-link"
        sandbox.mkdir(parents=True)
        link.symlink_to(code / "acme")
        record = {**going(ended(RUNS + 1, SEATS[2], time.time())), "repo": str(link)}
        kept = self.home.write(f".agentkit/runs/{record['run_id']}/run.json", record)
        moved = self.home.path / ".agentkit/state/runs-moved"
        moved.touch()
        self.menu.wait(row(SEATS[2], "● working"))
        link.unlink()                             # now the suite's own run, which no screen counts
        link.symlink_to(sandbox)
        self.menu.wait(self.not_working, bound=LATE)
        self.home.write(kept, {**record, "repo": str(code / "acme")})
        moved.touch()
        self.menu.wait(row(SEATS[2], "● working"))


if __name__ == "__main__":
    unittest.main()
