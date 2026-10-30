"""A reopened seat that dies again is reopened again after a pause, and the owner hears on its
third death.

On 24 Oct 2026 the OOM killer took a seat mid-turn; the tick reopened it, it died again within
two minutes, and it stayed dead for hours with nobody told: the once-per-death marker was cleared
only by a tick seeing the seat live, and none did.  Seats are now bounded as runs are: dead
again ten minutes after its reopen is a new death, reopened again, and the third inside an hour
is not reopened but asked of the owner, once, so the seat reads `needs you`.  A seat the owner
closed stays closed.  Each death here is inside its harness's warm-up, the kind ak leaves
to the tick (tests/test_key_exited_seat_comes_back.py).  The ten minutes are passed by
putting the seat's recorded reopens that much earlier, the times the bound reads, not waited out.
Black-box:
the program `AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py, beside
seats of tests/fixtures/akseat.py whose hooks are fired as Claude fires them
(tests/fixtures/hookdrive.py), each reopened by a scripted harness of fakeadapter.py.
"""

import json
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
SEATS = ("dying", "closed")
PAUSE = 660     # past the ten minutes after a reopen, well inside the hour


def conversation(n):
    return f"0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e2{n}"


def end(home, name, bound=30):
    """End the harness in the seat's pane as it starts, which tmux keeps, dead, as it keeps a
    seat's."""
    path = home.path / ".agentkit" / "state" / f"session-{name}.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "launched": time.time()}))
    done = home.tmux("respawn-pane", "-k", "-t", f"={name}:", "true")
    assert done.code == 0, done.err
    deadline = time.monotonic() + bound
    while dead(home, name) != "1":
        assert time.monotonic() < deadline, f"{name}'s pane never died"
        time.sleep(0.05)


def earlier(home, name, seconds):
    """Put the seat's recorded reopens `seconds` earlier, as if that long had passed since."""
    path = home.path / ".agentkit" / "state" / f"seat-{name}.json"
    marks = json.loads(path.read_text())
    path.write_text(json.dumps({**marks, "reopened_at": [at - seconds
                                                         for at in marks["reopened_at"]]}))


def dead(home, name):
    return home.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").out.strip()


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


def row(home, seat):
    """That seat's lines of `ak orch list`: its name, then the lines indented under it."""
    done = home.ak("orch", "list", "--why")
    assert done.code == 0, done.err
    lines, mine = [], False
    for line in done.out.splitlines():
        if not line.startswith(" "):
            mine = line.split()[:1] == [seat]
        if mine:
            lines.append(line)
    return "\n".join(lines)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ReopenedSeatDiesAgain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["opus"])
        fake = cls.fake = fakeadapter.install(home, claude="pass")["claude"]
        hooks = cls.hooks = Hooks(home)
        cls.seats = {}
        for n, name in enumerate(SEATS):
            seat = cls.seats[name] = Seat(home, name, record={"conversation": conversation(n)})
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/{conversation(n)}.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
            fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                                   str(seat.screen_file), str(seat.typed_file)]),
                        given=(conversation(n),))
            fired = hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=name, pane=seat)
            assert fired.code == 0, fired
        closed = home.ak("orch", "stop", "closed")
        assert closed.code == 0, closed.err
        cls.ticks, cls.reopens = [], []
        # first death: reopened, and told to go on
        end(home, "dying")
        cls.tick()
        cls.took(1)
        # dead again at once: the same death, left alone
        end(home, "dying")
        cls.tick()
        # still dead ten minutes after its reopen: a second death, reopened again
        earlier(home, "dying", PAUSE)
        cls.tick()
        cls.alive_again = dead(home, "dying")
        cls.took(2)
        # dead again, ten minutes on: the third inside the hour is the owner's
        end(home, "dying")
        earlier(home, "dying", PAUSE)
        cls.tick()
        cls.notice = state(home, "notify-dying.json")
        cls.row = row(home, "dying")
        cls.tick()
        cls.notice_after = state(home, "notify-dying.json")

    @classmethod
    def tick(cls):
        cls.ticks.append(cls.home.ak("watch", boxed=True))
        cls.reopens.append(cls.opened(conversation(0)))

    @classmethod
    def took(cls, count):
        """The reopened seat takes its line as Claude does, starting a turn."""
        line = cls.seats["dying"].wait_lines(count)[-1]
        fired = cls.hooks.fire("UserPromptSubmit", {"prompt": line}, seat="dying",
                               pane=cls.seats["dying"])
        assert fired.code == 0, fired

    @classmethod
    def opened(cls, conv):
        return [call["argv"][-1] for call in cls.fake.calls("interactive")].count(conv)

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_seat_dead_again_after_the_pause_is_reopened_again(self):
        self.assertEqual(self.reopens[:3], [1, 1, 2])
        self.assertEqual(self.alive_again, "0")
        self.assertEqual(len(self.seats["dying"].lines()), 2)

    def test_its_third_death_inside_the_hour_asks_the_owner_once(self):
        self.assertEqual(self.reopens[3:], [2, 2])
        self.assertEqual(dead(self.home, "dying"), "1")
        self.assertIsNotNone(self.notice, "the owner was not asked")
        self.assertEqual((self.notice.get("session"), self.notice.get("kind")),
                         ("dying", "needs"))
        self.assertEqual(self.notice_after, self.notice)
        self.assertIn("needs you", self.row)

    def test_a_seat_the_owner_closed_stays_closed(self):
        self.assertEqual(self.opened(conversation(1)), 0)
        self.assertEqual(self.seats["closed"].lines(), [])
        self.assertIsNone(state(self.home, "notify-closed.json"))


if __name__ == "__main__":
    unittest.main()
