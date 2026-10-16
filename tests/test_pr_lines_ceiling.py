"""A first review's line ceiling is read each week off how often changes of each size ended merged.

Changes go in bands of `task.BAND` lines by what their first review read; the ones up to a
band are the measure.  With the small changes unmeasured the ceiling is
`task.PR_LINES_UNMEASURED`; a band that merges less often than the small ones sets the ceiling
at its bottom; otherwise the ceiling is the top of the first band not yet measured, never under
the unmeasured one.  Only the `task.WEEKS` before this week count, and a change counts once,
merged when any of its runs merged.  Offline: a sandbox HOME's history.
"""

import unittest
from datetime import datetime, timezone

from fixtures.sandbox import Sandbox
from agentkit import history, task as taskfile

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc).timestamp()          # a Wednesday
LAST_WEEK = datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp()


class PrLinesCeiling(Sandbox):
    def change(self, name, lines, merged, at=LAST_WEEK, runs=("pass",)):
        """One change of `lines` first-reviewed lines whose runs ended in `runs`, in order."""
        for number, state in enumerate(runs):
            run_id = f"20261001-{name}-{number}"
            history.start_run(run_id, repo="acme", change=name, started_at=at - 3600)
            if number == 0:
                history.update_run(run_id, first_review_lines=lines)
            last = number == len(runs) - 1
            history.finish_run(run_id, final_state=state, verdict=state.upper(), finished_at=at,
                               changed_lines=lines if merged and last else None)

    def band(self, band, count, merged, at=LAST_WEEK):
        for k in range(count):
            self.change(f"b{band}-{k}", band * taskfile.BAND + 50, k < merged, at,
                        ("pass",) if k < merged else ("fail",))

    def ceiling(self):
        return taskfile.pr_lines_ceiling(now=NOW)

    def test_with_no_history_the_ceiling_is_the_unmeasured_one(self):
        self.assertEqual(self.ceiling(), taskfile.PR_LINES_UNMEASURED)
        self.band(0, taskfile.MEASURED - 1, taskfile.MEASURED - 1)      # small changes, too few
        self.band(1, 30, 30)
        self.assertEqual(self.ceiling(), taskfile.PR_LINES_UNMEASURED)

    def test_the_ceiling_tries_one_band_past_the_ones_that_merge_as_often(self):
        self.band(0, 40, 36)
        for band in (1, 2, 3):
            self.band(band, 30, 26)                 # 87% against 90%: as often, within noise
        self.assertEqual(self.ceiling(), 500)       # 401-500 is the band being tried
        self.band(4, 30, 26)
        self.band(5, 30, 26)
        self.assertEqual(self.ceiling(), 700)

    def test_a_band_that_merges_less_often_sets_the_ceiling_at_its_bottom(self):
        self.band(0, 40, 36)
        self.band(1, 30, 26)
        self.band(3, 30, 12)                        # 40%: 301-400 merges less often
        self.assertEqual(self.ceiling(), 300)
        self.band(2, 30, 12)
        self.assertEqual(self.ceiling(), 200)

    def test_only_the_weeks_before_this_one_count(self):
        self.band(0, 40, 36)
        self.band(1, 30, 12, at=NOW - 3600)                                  # this week
        self.band(2, 30, 12, at=LAST_WEEK - taskfile.WEEKS * 7 * 86400)      # aged out
        self.assertEqual(self.ceiling(), taskfile.PR_LINES_UNMEASURED)

    def test_a_change_counts_once_merged_when_any_of_its_runs_merged(self):
        for k in range(30):
            self.change(f"retried-{k}", 350, True, runs=("fail", "stopped", "pass"))
        self.assertEqual(history.first_reviews(0, NOW).count((350, True)), 30)
        # a change with a run still going has no ending yet
        history.start_run("20261001-going-0", repo="acme", change="retried-0", started_at=LAST_WEEK)
        self.assertEqual(history.first_reviews(0, NOW).count((350, True)), 29)


if __name__ == "__main__":
    unittest.main(verbosity=2)
