"""A seat that died while its `ak wait` stood is reopened once what it waited on ends.

On 24 Oct 2026 a seat was killed while it waited on a pull request; it had no run of its own,
so nothing reopened it, its wait ended unheard, and it stayed dead for 5.8 hours.  Now the tick
that sees a gone seat's wait end reopens it on its own conversation with that wait's line,
typed in once.  A seat the owner closed stays closed.  Black-box: the program `AK_BIN` names
runs `ak wait` and `ak watch` from outside through tests/fixtures/akbin.py, beside seats of
tests/fixtures/akseat.py, the dead one reopened by a scripted harness of fakeadapter.py.
"""

import re
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

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
RUN = "20261024-0300-fix-api"
SEATS = ("killed", "closed")


def conversation(n):
    return f"0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e2{n}"


def dead(home, name):
    return home.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").out.strip()


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class GoneSeatHearsItsWaitEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["opus"])
        fake = fakeadapter.install(home, claude="pass")["claude"]
        # a run no seat launched, going: its line holds it until the lander ends it
        home.write(f".agentkit/runs/{RUN}/run.json",
                   {"run_id": RUN, "title": "fix-api", "state": "waiting",
                    "waiting_on": {"line": "acme/api"}})
        cls.seats = {}
        for n, name in enumerate(SEATS):
            seat = cls.seats[name] = Seat(home, name, record={"conversation": conversation(n)})
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/{conversation(n)}.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
            fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                                   str(seat.screen_file), str(seat.typed_file)]),
                        given=(conversation(n),))
            waited = home.ak("wait", RUN, env={"AGENTKIT_SESSION": name})
            assert waited.code == 0, waited.out + waited.err
        closed = home.ak("orch", "stop", "closed")
        assert closed.code == 0, closed.err
        done = home.tmux("respawn-pane", "-k", "-t", "=killed:", "true")
        assert done.code == 0, done.err
        deadline = time.monotonic() + 30
        while dead(home, "killed") != "1":
            assert time.monotonic() < deadline, "the killed seat's pane never died"
            time.sleep(0.05)
        cls.before = home.ak("watch", boxed=True)
        cls.opened_before = [call["argv"][-1] for call in fake.calls("interactive")]
        home.write(f".agentkit/runs/{RUN}/run.json",
                   {"run_id": RUN, "title": "fix-api", "state": "pass", "verdict": "PASS",
                    "finished_at": time.time()})
        cls.tick = home.ak("watch", boxed=True)
        cls.after = dead(home, "killed")
        cls.told = cls.seats["killed"].wait_lines(1)
        cls.again = home.ak("watch", boxed=True)
        cls.opened = [call["argv"][-1] for call in fake.calls("interactive")]

    def test_every_tick_exits_zero(self):
        for done in (self.before, self.tick, self.again):
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_gone_seat_still_waiting_is_left_gone(self):
        self.assertEqual(self.opened_before, [])

    def test_a_gone_seat_whose_wait_ends_comes_back_and_hears_that_line_once(self):
        self.assertEqual(self.after, "0")
        self.assertEqual(self.opened.count(conversation(0)), 1, self.opened)
        line, = self.told
        self.assertIn(f"run {RUN} ended PASS; your wait is over", line)
        self.assertEqual(self.seats["killed"].lines(), self.told)

    def test_a_seat_the_owner_closed_stays_closed(self):
        self.assertNotIn(conversation(1), self.opened)
        self.assertEqual(self.seats["closed"].lines(), [])


if __name__ == "__main__":
    unittest.main()
