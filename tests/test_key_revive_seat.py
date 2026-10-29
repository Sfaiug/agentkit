"""A seat that died while a run it launched is still going is reopened by the tick, and told.

The run will hand its ending back to its seat, so a seat whose harness died under it (a crash,
a kill, a reboot) is reopened on its own conversation, in its own session, and told in one
line that the run is still going; the owner is not asked.  Once per death: a seat seen live
again and dying again is reopened again.  A seat ak cannot reopen is one of the few failures
only the owner can fix, so it pages them, once.  Each death here is inside its harness's
warm-up, the kind ak leaves to the tick (tests/test_key_exited_seat_comes_back.py).  Black-box:
the program `AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py, beside a
seat of tests/fixtures/akseat.py and a run whose turn a scripted harness of fakeadapter.py holds,
paging tests/fixtures/sink.py.
"""

import json
import re
import shlex
import socket
import sys
from pathlib import Path
import time
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat
from fixtures.gitrig import Rig
from fixtures.sink import Sink

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
CONVERSATION = "0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e1f"


def going(test, home, seat, *, opens):
    """A Home whose seat acme launched a run whose turn never ends, and whose harness, when ak
    opens the seat, `opens` with: an adapter answer for its `interactive` verb."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # The tick asks the public boards over HTTP and fetches the checkout it runs from: only
    # the test's own sink is reached past a proxy nobody listens on, and git speaks to files.
    passed = urlsplit(test.sink.url).netloc
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"), no_proxy=passed,
                    NO_PROXY=passed, GIT_ALLOW_PROTOCOL="file")
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus"])
    adapters = home.root / "adapters"
    held = adapters / "held"
    hold = {"sh": f"touch '{held}'; while [ -d '{adapters}' ]; do sleep 0.1; done"}
    test.fake = fakeadapter.install(home, claude=hold)["claude"]
    test.fake.answer("interactive", *opens)
    loop = home.spawn("run", str(taskfile.write(home, rig.path)), "--no-merge",
                      env={"AGENTKIT_SESSION": seat.name}, boxed=True)
    deadline = time.monotonic() + 60
    while not held.exists():
        assert loop.poll() is None, home.log("spawn-1.err").read_text()
        assert time.monotonic() < deadline, "the run never started its turn"
        time.sleep(0.1)
    test.run_id = taskfile.only_run(home).name


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


def dead(home, name):
    return home.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").out.strip()


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class SeatRevived(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        seat = Seat(home, "acme", record={"conversation": CONVERSATION}, planned=True)
        # Claude files a workspace's conversations under its path, each character that is not
        # a letter or a digit a dash: this one it has opened, so it is resumed, not started.
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl",
                   '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        # reopened, the harness shows the seat's screen again and keeps what is typed into it
        going(cls, home, seat, opens=[shlex.join([sys.executable, str(PANE),
                                                  str(seat.screen_file), str(seat.typed_file)])])
        cls.seat, cls.ticks, cls.told, cls.after = seat, [], [], []
        for death in range(2):
            if death:
                # a tick that sees it live: the next death is a new one
                cls.ticks.append(home.ak("watch", boxed=True))
            end(home, "acme")
            cls.ticks.append(home.ak("watch", boxed=True))
            cls.after.append(dead(home, "acme"))
            cls.told.append(seat.wait_lines(death + 1)[death:])
        cls.opened = cls.fake.calls("interactive")

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_the_seat_comes_back_in_its_own_session_on_its_own_conversation(self):
        self.assertEqual(self.after[0], "0")
        argv = self.opened[0]["argv"]
        self.assertEqual(argv[-1], CONVERSATION, argv)
        self.assertNotIn("new", argv)

    def test_the_seat_is_told_in_one_line_that_its_run_is_still_going(self):
        line, = self.told[0]
        self.assertIn(self.run_id, line)
        self.assertIn("still going", line)

    def test_a_seat_seen_live_that_dies_again_is_reopened_again(self):
        self.assertEqual(self.after[1], "0")
        self.assertEqual(len(self.opened), 2, self.opened)
        self.assertEqual(self.told[1], self.told[0])

    def test_nobody_is_paged_for_a_seat_ak_brought_back(self):
        self.assertEqual(self.sink.pages(), [])


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class SeatNotReopened(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        # tmux lost the seat, and its harness gives no command to open it with
        going(cls, home, Seat(home, "acme", alive=False, planned=True), opens=["", 1])
        cls.ticks = [home.ak("watch", boxed=True), home.ak("watch", boxed=True)]
        cls.opened = cls.fake.calls("interactive")

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_ak_tries_to_reopen_the_seat_once_for_its_death(self):
        self.assertEqual(len(self.opened), 1, self.opened)

    def test_the_owner_is_paged_once_that_the_seat_needs_them(self):
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · acme"])


if __name__ == "__main__":
    unittest.main()
