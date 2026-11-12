"""An ending that waited for its seat mid-turn reopens that seat once it is gone, however old.

On 10 Nov 2026 one waited eight hours: ak took it for history and asked the owner to reopen a
seat it reopened itself two seconds later.  Black-box, as tests/test_key_revive_seat.py.
"""

import shlex
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat
from test_key_revive_seat import PROXIES

RUN = "20261110-0900-fix-api"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AWaitedEndingReopensItsSeat(unittest.TestCase):
    def test_the_seat_comes_back_told_once_and_the_owner_is_not_asked(self):
        with Home() as home, socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))    # a port nobody listens on: the tick reaches no board
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
            akconfig.write(home, ["opus"])
            fake = fakeadapter.install(home, claude="pass")["claude"]
            seat = Seat(home, "acme", alive=False)      # tmux lost it: only its record is left
            fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                                   str(seat.screen_file), str(seat.typed_file)]))
            home.write(f".agentkit/runs/{RUN}/run.json", {
                "run_id": RUN, "title": "fix-api", "launched_session": "acme", "state": "fail",
                "finished_at": time.time() - 7200, "handback_pending": True})
            for _ in range(2):      # the second tick has nothing left to say
                done = home.ak("watch", boxed=True)
                self.assertEqual(done.code, 0, done.out + done.err)
            line, = seat.wait_lines(1)
            self.assertIn(f"run {RUN} finished FAIL", line)
            self.assertFalse((home.path / ".agentkit/state/notify-acme.json").exists())


if __name__ == "__main__":
    unittest.main()
