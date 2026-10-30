"""A seat waiting on its own run hears that run's ending once.

The run's hand-back carries the verdict, the pull request and the result, so a seat whose `ak
wait` names that run, or the pull request it lands (waited on as the run), gets that one line: the tick's wait pass
(`watch.wait_over`) types nothing while the hand-back is on its way and marks the wait told once
it is in, or once its seat's own `ak wait` on the ended run has printed it.  A routine ending,
recorded and never typed, still ends the wait with its own line.
The fixture is fixtures.seats: a temporary HOME, a fake tmux and pane.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from fixtures.seats import LINE, NOW, RUN, SEAT, Seats
from agentkit import config, handback, orch, record, stop, watch

PR = "https://github.com/acme/parser/pull/7"


class OneLinePerRunEnd(Seats):
    def setUp(self):
        super().setUp()
        self.wait_line()
        self.directory = config.RUNS / RUN
        patcher = patch.object(orch, "watching", side_effect=lambda name: name == SEAT)
        patcher.start()
        self.addCleanup(patcher.stop)

    def other(self, **state):
        """A run another seat launched."""
        directory = config.RUNS / "20260101-0910-acme-review"
        directory.mkdir(exist_ok=True)
        record.save_state(directory, {"run_id": directory.name, "launched_session": "fix-api",
                                      "started_at": NOW - 600, **state})

    def end(self, **state):
        """The run ends as `state` says, and its ending is announced to the seat."""
        record.save_state(self.directory, dict(record.read_state(self.directory), **state))
        handback.announce(record.read_state(self.directory), self.directory, lambda _: None,
                          self.cfg)

    def test_a_wait_on_its_run_hears_only_the_hand_back(self):
        record.save_state(self.directory, dict(record.read_state(self.directory),
                                               state="running", finished_at=None))
        self.tick()     # still going: nothing to say
        record.save_state(self.directory, dict(record.read_state(self.directory), state="fail",
                                               verdict="FAIL", merged=False,
                                               finished_at=NOW - 60))
        self.tick()     # ended, its hand-back not yet typed: the wait pass waits for it
        self.assertEqual(self.typed, [])
        self.assertFalse(self.told())
        self.end()
        self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertTrue(self.typed[0].startswith(f"run {RUN} finished FAIL"))
        self.assertTrue(self.told())
        self.assertEqual(watch.seat_read(SEAT)["wait"]["over"], f"run {RUN} ended FAIL")

    def test_a_wait_on_the_pull_request_it_lands_hears_only_the_hand_back(self):
        watch.seat_write(SEAT, wait={"on": PR, "kind": "pr", "at": NOW - 300})
        # another seat's review of it ended last: the merge is still this run's ending
        self.other(state="fail", review_pr=PR, finished_at=NOW)
        with (patch.object(watch, "gh_json", return_value=(
                {"state": "MERGED", "number": 7, "mergeCommit": {"oid": "abc123"}}, "")),
              patch.object(stop, "owed", return_value=True)):      # its plan owes work
            # merged, the run not yet ended: its hand-back is still to come
            record.save_state(self.directory, dict(record.read_state(self.directory), pr=PR,
                                                   state="running", finished_at=None))
            self.tick()
            self.assertEqual(self.typed, [])
            self.end(state="pass", finished_at=NOW - 60)
            self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertTrue(self.typed[0].startswith(f"run {RUN} finished "))   # the hand-back
        self.assertTrue(self.told())
        self.assertEqual(watch.seat_read(SEAT)["wait"]["over"], "PR #7 merged as abc123")

    def test_ak_wait_on_the_pull_request_its_run_lands_hears_only_the_hand_back(self):
        record.save_state(self.directory, dict(record.read_state(self.directory), pr=PR,
                                               state="running", merged=False, finished_at=None))
        gh = {"state": "OPEN", "number": 7, "mergeCommit": None}
        with (patch.object(watch, "gh_json", side_effect=lambda *_a, **_kw: (gh, "")),
              patch.object(stop, "owed", return_value=True),
              patch.dict(os.environ, {config.SESSION_ENV: SEAT})):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(watch.wait_main([PR]), 0)
            # GitHub says merged before the lander's gh call returns and it saves merged
            gh.update(state="MERGED", mergeCommit={"oid": "abc123"})
            self.tick()
            self.assertEqual(self.typed, [])
            self.end(state="pass", merged=True, finished_at=NOW - 60)
            self.tick()
        self.assertEqual(len(self.typed), 1)
        self.assertTrue(self.typed[0].startswith(f"run {RUN} finished "))   # the hand-back
        self.assertTrue(self.told())

    def test_a_pull_request_closed_after_its_hand_back_gets_its_own_line(self):
        watch.seat_write(SEAT, wait={"on": PR, "kind": "pr", "at": NOW - 300})
        self.other(state="running", review_pr=PR)
        gh = {"state": "OPEN", "number": 7, "mergeCommit": None}
        with patch.object(watch, "gh_json", side_effect=lambda *_a, **_kw: (gh, "")):
            self.end(state="fail", verdict="FAIL", merged=False, review_pr=PR)
            self.tick()     # another seat's review still holds the wait
            gh["state"] = "CLOSED"
            self.tick()
        self.assertEqual(len(self.typed), 2)
        self.assertEqual(self.typed[1],
                         "PR #7 closed without merging; your wait is over. Decide the next step.")
        self.assertTrue(self.told())

    def test_its_ending_read_in_its_ak_wait_ends_the_wait_untyped(self):
        record.save_state(self.directory, dict(record.read_state(self.directory), state="fail",
                                               verdict="FAIL", merged=False,
                                               handback_pending=True))   # deferred: busy seat
        with (patch.dict(os.environ, {config.SESSION_ENV: SEAT}),
              redirect_stderr(io.StringIO()) as err):
            self.assertEqual(watch.wait_main([RUN]), 1)
        self.assertIn(f"run {RUN} finished FAIL", err.getvalue())
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertTrue(self.told())

    def test_a_routine_ending_still_ends_the_wait_with_its_line(self):
        self.end()      # merged, while the seat owes nothing: recorded, not typed
        self.assertEqual(record.read_state(self.directory)["handback_note"],
                         handback.ROUTINE_NOTE)
        self.tick()
        self.assertEqual(self.typed, [LINE])
        self.assertTrue(self.told())


if __name__ == "__main__":
    unittest.main(verbosity=2)
