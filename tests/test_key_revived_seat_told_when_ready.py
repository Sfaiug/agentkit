"""A seat the tick reopens is told its line once its screen shows its prompt, however late.

On 24 Oct 2026 a seat was reopened on a host swapping at a load above 250; its harness had not
drawn its prompt within the fixed 10 s ak gave it, the one send was not confirmed, and the owner
was asked to type the line ak could have typed a minute later.  The line is now ak's until the
seat takes it: typed at the seat's quiet prompt, never onto what the owner typed there, and the
owner hears only of a seat ak could not reopen.  Black-box: the program `AK_BIN` names runs
`ak watch` from outside through tests/fixtures/akbin.py, beside a seat of tests/fixtures/akseat.py
and a run whose turn a scripted harness of fakeadapter.py holds, paging tests/fixtures/sink.py;
reopened, the seat's harness drops every key for DRAWS_AFTER seconds before it draws its prompt.
"""

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
DRAWS_AFTER = 60
# A harness starting up: it reads and drops every key until it draws, then is the seat's pane.
STARTING = """
import os, select, sys, time, tty
tty.setraw(0)
os.write(1, b"Resuming the conversation...")
begun = time.monotonic()
while time.monotonic() < begun + float(sys.argv[1]) or select.select([0], [], [], 0)[0]:
    if select.select([0], [], [], 0.1)[0]:
        os.read(0, 4096)
os.execv(sys.executable, [sys.executable, *sys.argv[2:]])
"""
DRAFT = "half a thought"


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
    """End the harness in the seat's pane, which tmux keeps, dead, as it keeps a seat's."""
    done = home.tmux("respawn-pane", "-k", "-t", f"={name}:", "true")
    assert done.code == 0, done.err
    deadline = time.monotonic() + bound
    while home.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").out.strip() != "1":
        assert time.monotonic() < deadline, f"{name}'s pane never died"
        time.sleep(0.05)


def until(seat, drawn, bound):
    """Wait until the pane shows `drawn`."""
    deadline = time.monotonic() + bound
    while drawn not in seat.capture():
        assert time.monotonic() < deadline, f"the seat never drew {drawn!r}:\n{seat.capture()}"
        time.sleep(0.2)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ToldWhenReady(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        cls.seat = seat = Seat(home, "acme", record={"conversation": CONVERSATION}, planned=True)
        # Claude files a workspace's conversations under its path, each character that is not
        # a letter or a digit a dash: this one it has opened, so it is resumed, not started.
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl",
                   '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        going(cls, home, seat, opens=[shlex.join([
            sys.executable, "-c", STARTING, str(DRAWS_AFTER), str(PANE), str(seat.screen_file),
            str(seat.typed_file)])])
        end(home, "acme")
        cls.ticks = [home.ak("watch", boxed=True)]          # reopens it
        cls.ticks.append(home.ak("watch", boxed=True))      # finds it still starting
        cls.starting = seat.lines()
        until(seat, "bypass permissions on", DRAWS_AFTER + 60)
        # the owner types into its composer and has not sent it
        home.tmux("send-keys", "-t", "=acme:", "-l", DRAFT)
        until(seat, DRAFT, 30)
        cls.ticks.append(home.ak("watch", boxed=True))
        cls.drafted, cls.draft_typed = seat.lines(), seat.typed()
        # ... and takes it back out
        home.tmux("send-keys", "-t", "=acme:", "C-u")
        deadline = time.monotonic() + 30
        while DRAFT in seat.capture():
            assert time.monotonic() < deadline, "the draft never left the composer"
            time.sleep(0.1)
        cls.ticks.append(home.ak("watch", boxed=True))
        cls.told = seat.wait_lines(1)
        cls.ticks.append(home.ak("watch", boxed=True))
        cls.after = seat.lines()

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_nothing_is_typed_while_the_harness_is_starting(self):
        self.assertEqual(self.starting, [])

    def test_the_owners_unsent_text_is_never_sent_or_typed_onto(self):
        self.assertEqual(self.drafted, [])
        self.assertEqual(self.draft_typed, DRAFT)

    def test_the_seat_is_told_its_line_once_its_prompt_shows_and_only_once(self):
        line, = self.told
        self.assertIn(self.run_id, line)
        self.assertIn("still going", line)
        self.assertEqual(self.after, self.told)
        self.assertEqual(len(self.fake.calls("interactive")), 1)

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

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_the_owner_is_paged_once_that_the_seat_needs_them(self):
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · acme"])


if __name__ == "__main__":
    unittest.main()
