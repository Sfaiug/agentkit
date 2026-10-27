"""A seat whose harness died mid-turn is reopened by the next tick, with no run going and no
reboot.

On 24 Oct 2026 the OOM killer ended a seat while it waited on four background agents; it had no
run going, so it sat dead for two hours until the owner opened it and typed "continue".  Every
tick now judges a gone seat as a reboot does: one cut off in its turn, a Stop on background
agents among them, is reopened on its own conversation and told to go on, once per death.  One
the owner closed stays closed; one that died idle is
tests/test_key_dead_seat_holding_work_comes_back.py's.  Black-box: the program `AK_BIN` names
runs `ak watch` from outside through tests/fixtures/akbin.py, beside seats of
tests/fixtures/akseat.py whose hooks are fired as Claude fires them (tests/fixtures/hookdrive.py),
each reopened by a scripted harness of fakeadapter.py.
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
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
AGENT = {"id": "a1", "type": "subagent", "status": "running", "description": "slow check"}
SHELL = {"id": "b1", "type": "shell", "status": "running", "description": "sleep 600"}
SEATS = ("midturn", "agents", "closed")
MIDTURN = "in the middle of a turn"


def conversation(n):
    return f"0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1{n}"


def end(home, name, bound=30):
    """End the harness in the seat's pane, which tmux keeps, dead, as it keeps a seat's."""
    done = home.tmux("respawn-pane", "-k", "-t", f"={name}:", "true")
    assert done.code == 0, done.err
    deadline = time.monotonic() + bound
    while dead(home, name) != "1":
        assert time.monotonic() < deadline, f"{name}'s pane never died"
        time.sleep(0.05)


def dead(home, name):
    return home.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").out.strip()


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class DeadSeatWithWork(unittest.TestCase):
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
        hooks, cls.seats = Hooks(home), {}
        for n, name in enumerate(SEATS):
            seat = cls.seats[name] = Seat(home, name, record={"conversation": conversation(n)})
            # Claude files a workspace's conversations under its path, each character that is
            # not a letter or a digit a dash: this one it has opened, so it is resumed.
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/{conversation(n)}.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
            # reopened, the harness shows the seat's screen again and keeps what is typed in
            fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                                   str(seat.screen_file), str(seat.typed_file)]),
                        given=(conversation(n),))
            fired = hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=name, pane=seat)
            assert fired.code == 0, fired
        fired = hooks.fire("Stop", {"background_tasks": [AGENT, SHELL], "transcript_path": "",
                                    "last_assistant_message": "Started it."},
                           seat="agents", pane=cls.seats["agents"])
        assert fired.code == 0, fired
        closed = home.ak("orch", "stop", "closed")
        assert closed.code == 0, closed.err
        for name in ("midturn", "agents"):
            end(home, name)
        cls.tick = home.ak("watch", boxed=True)
        cls.after = {name: dead(home, name) for name in ("midturn", "agents")}
        cls.told = {name: cls.seats[name].wait_lines(1) for name in ("midturn", "agents")}
        # dead again before any tick saw them live: the same death, not a new one
        for name in ("midturn", "agents"):
            end(home, name)
        cls.again = home.ak("watch", boxed=True)
        cls.opened = [call["argv"][-1] for call in fake.calls("interactive")]

    def test_every_tick_exits_zero(self):
        for done in (self.tick, self.again):
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_seat_that_died_mid_turn_comes_back_on_its_conversation_and_is_told_once(self):
        self.assertEqual(self.after["midturn"], "0")
        self.assertEqual(self.opened.count(conversation(0)), 1, self.opened)
        line, = self.told["midturn"]
        self.assertIn(MIDTURN, line)
        self.assertEqual(self.seats["midturn"].lines(), self.told["midturn"])

    def test_a_seat_that_died_on_background_agents_comes_back_the_same_way(self):
        self.assertEqual(self.after["agents"], "0")
        self.assertEqual(self.opened.count(conversation(1)), 1, self.opened)
        line, = self.told["agents"]
        self.assertIn(MIDTURN, line)
        self.assertIn("background work: subagent, shell", line)
        self.assertEqual(self.seats["agents"].lines(), self.told["agents"])

    def test_a_seat_the_owner_closed_stays_closed(self):
        self.assertNotIn(conversation(2), self.opened)
        self.assertEqual(self.seats["closed"].lines(), [])


if __name__ == "__main__":
    unittest.main()
