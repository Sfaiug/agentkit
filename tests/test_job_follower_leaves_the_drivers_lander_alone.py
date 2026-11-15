"""A job's follower leaves the lander a run's driver starts on leaving for the landing line the
picker's interval to itself, however long it followed the run before.  Offline."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, job, land, record  # noqa: E402
from fixtures.clock import Clock
from fixtures.sandbox import Sandbox


class FollowerLeavesTheDriversLanderAlone(Sandbox):
    def test_a_run_parked_after_a_long_follow_gets_its_lander_an_interval_after_the_first_look(self):
        run_dir = config.RUNS / "fix-api"
        run_dir.mkdir()
        record.save_state(run_dir, {"run_id": run_dir.name, "state": "running",
                                    **record.process_owner()})
        left = 1000 + 2 * job.JOB_PICKER_INTERVAL   # the driver ran past the interval first
        now, starts = [1000], []

        class Followed(Exception):
            pass

        def sleep(seconds):
            now[0] += seconds
            if now[0] == left:   # its driver parks it in the line, which starts the lander, and leaves
                record.save_state(run_dir, {"run_id": run_dir.name, "state": "waiting",
                                            "waiting_on": {"line": "acme-main"}, "pid": None})
            if now[0] > left + job.JOB_PICKER_INTERVAL:
                raise Followed

        clock = Clock(sleep)
        clock.time = lambda: now[0]
        with patch.object(job, "time", clock), self.assertRaises(Followed), \
                patch.object(land, "start_line", side_effect=lambda line: starts.append((now[0], line))):
            job.job_await(run_dir)
        # the driver's as it left, none at the follower's first look, the follower's an interval on
        line = config.RUNS / "acme-main"
        self.assertEqual(starts, [(left, line), (left + job.JOB_PICKER_INTERVAL, line)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
