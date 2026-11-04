"""A changed seat or run file shows at the next refresh."""

import json
import time
import unittest

from test_key_idle_screen_reads_only_what_changed import RUNS, OpenScreen, ended, row


class IdleScreenReadsOnlyWhatChanged(OpenScreen):
    def going(self, run, record):
        """That run going, touching the mark every open screen reads again on, as a run's every
        move does (`handback.redress_seat`)."""
        self.home.write(run, {**record, "state": "running", "verdict": None, "merged": False,
                              "step": "executor", "started_at": time.time(), "finished_at": None})
        (self.home.path / ".agentkit/state/runs-moved").touch()

    def test_2_a_changed_seat_or_run_file_shows_at_the_next_refresh(self):
        # a seat tmux lost no longer holds a conversation to resume: it has no row to reopen
        gone = self.home.path / ".agentkit/state/session-acme-09.json"
        record = json.loads(gone.read_text())
        del record["conversation"]
        self.home.write(gone, record)
        run = self.runs["acme-03"]
        self.going(run, json.loads(run.read_text()))
        # A screen reads one refresh at a time.  A new run of acme-15's goes after the changes,
        # so the refresh drawing it ended after they landed; acme-21's goes once that is drawn,
        # so the refresh drawing it began after them, and shows them both however soon it came.
        for n, witness in enumerate(("acme-15", "acme-21"), RUNS):
            record = ended(n, witness, time.time())
            self.going(self.home.path / f".agentkit/runs/{record['run_id']}/run.json", record)
            screen = self.menu.wait(row(witness, "● working"))
        self.assertIsNone(row("acme-09")(screen))
        self.assertTrue(row("acme-03", "● working")(screen))


if __name__ == "__main__":
    unittest.main()
