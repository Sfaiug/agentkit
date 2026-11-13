"""A job's ending that waited for its seat reaches that seat after it was renamed.

The job's record names the seat as it was launched; the tick types the line into the seat by the
name it has now, at its prompt, and never asks the owner instead.  Black-box, as
tests/test_key_a_waited_ending_reopens_its_seat.py.
"""

import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from test_key_revive_seat import PROXIES

LINE = "job job-acme: 1 task needs you. Decide the next step."


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ARenamedSeatTakesItsJobsEnding(unittest.TestCase):
    def test_the_seat_is_told_by_its_new_name_and_the_owner_is_not_asked(self):
        with Home() as home, socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))    # a port nobody listens on: the tick reaches no board
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
            akconfig.write(home, ["opus"])
            seat = Seat(home, "beta")
            # what `ak orch rename acme beta` leaves at the old name (tests/test_key_orch_rename.py)
            home.write(".agentkit/state/session-acme.json", {"renamed": "beta"})
            home.write(".agentkit/jobs/job-acme/job.json", {
                "job_id": "job-acme", "seat": "acme", "finished_at": time.time() - 60,
                "tasks": [], "handback_pending": LINE})
            done = home.ak("watch", boxed=True)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(seat.wait_lines(1), [LINE])
            for name in ("acme", "beta"):
                self.assertFalse((home.path / f".agentkit/state/notify-{name}.json").exists())


if __name__ == "__main__":
    unittest.main()
