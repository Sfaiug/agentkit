"""A seat whose harness ends without ak ending it comes back at once, in its pane, on its own
conversation.

On 28 Oct 2026 the owner typed `/exit` into a seat by accident.  `remain-on-exit` kept its pane,
dead, and a dead pane takes no keys: the only way back was Ctrl-b m and the seat's number.  A
harness that ends without ak ending it -- an exit, a crash, a kill from outside -- now comes back
within seconds the way its number opens it: in the same pane, on the conversation its record
holds.  `ak orch stop` still ends a seat, a seat the owner closed stays down, and a harness that
ends inside its warm-up stays down, so one that cannot start never loops; its pane says in one
line how to open it again.  A server started before any of this gets the same from the tick.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on a real
tmux of the test's own, each seat's harness a TUI of tests/fixtures/fakeadapter.py that quits at
Enter, or at once where its folder says so.
"""

import json
import os
import re
import signal
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

TUI = "sh -c '[ -e quits-at-once ] || read line'"
SEATS = ("quit", "crash", "stopped", "closed", "early")
CONVERSATION = "5e1f0a2b-3c4d-4e6f-8a9b-0c1d2e3f4a5b"
BOUND = 60      # seconds a seat has to come back
MARGIN = 3      # ... and an end left alone has beyond those that came back


def opened_on_its_own(home, name, cwd):
    """Claude files a workspace's conversations under its path, each character that is not a
    letter or a digit a dash: the seat's has been opened, so it is resumed and not opened."""
    folder = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    conversation = record(home, name)["conversation"]
    home.write(f".claude/projects/{folder}/{conversation}.jsonl",
               '{"type":"user","message":{"role":"user","content":"hello"}}\n')


def record(home, name):
    return json.loads((home.path / f".agentkit/state/session-{name}.json").read_text())


def says(home, name, form):
    return home.tmux("display-message", "-p", "-t", f"={name}:", form).out.strip()


def launches(fake, conversation):
    """Each launch of the harness on that conversation: its arguments after model and effort."""
    return [call["argv"][2:] for call in fake.calls("interactive")
            if conversation in call["argv"]]


def wait(until, what):
    deadline = time.monotonic() + BOUND
    while not until():
        if time.monotonic() > deadline:
            raise AssertionError(what)
        time.sleep(0.1)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AHarnessThatEndsWithoutAk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.fake = fakeadapter.install(home, claude="pass")["claude"]
        cls.fake.answer("interactive", TUI)
        for name in SEATS:
            cwd = home.path / "code" / name
            cwd.mkdir(parents=True)
            if name == "early":
                (cwd / "quits-at-once").touch()
            done = home.ak("orch", name, "--model", "opus", "--workers", "opus", tty=True,
                           cwd=cwd)
            assert done.code == 0, done.err
            if name != "early":
                opened_on_its_own(home, name, cwd)
                # launched an hour ago: past any warm-up
                path = home.path / f".agentkit/state/session-{name}.json"
                path.write_text(json.dumps({**record(home, name),
                                            "launched": record(home, name)["launched"] - 3600}))
        cls.pane = {name: says(home, name, "#{pane_id}") for name in ("quit", "crash")}
        cls.records = {name: record(home, name) for name in SEATS}
        stopped = home.ak("orch", "stop", "stopped")
        assert stopped.code == 0, stopped.err
        # closed by the owner with its session left standing, as a pause script closes one
        seat = home.path / ".agentkit/state/seat-closed.json"
        marks = json.loads(seat.read_text()) if seat.exists() else {}
        seat.write_text(json.dumps({**marks, "stopped_at": time.time(), "closed_by_owner": True}))
        # the owner's `/exit`, and a closed seat's harness quitting; then a crash
        for name in ("quit", "closed"):
            assert home.tmux("send-keys", "-t", f"={name}:", "Enter").code == 0
        os.kill(int(says(home, "crash", "#{pane_pid}")), signal.SIGKILL)
        for name in ("quit", "crash"):
            wait(lambda: len(launches(cls.fake, cls.records[name]["conversation"])) == 2
                 and says(home, name, "#{pane_dead}") == "0", f"{name} never came back")
        time.sleep(MARGIN)

    def assertBackOnItsConversation(self, name):
        conversation = self.records[name]["conversation"]
        self.assertEqual(launches(self.fake, conversation), [[conversation, "new"],
                                                             [conversation]])
        self.assertEqual(says(self.home, name, "#{pane_dead}"), "0")
        # the same pane, which ak goes on knowing as the seat's
        self.assertEqual(says(self.home, name, "#{pane_id}\t#{@ak_harness_pane}"),
                         f"{self.pane[name]}\t{self.pane[name]}")
        self.assertEqual(record(self.home, name)["conversation"], conversation)

    def assertStaysDown(self, name):
        conversation = self.records[name]["conversation"]
        self.assertEqual(launches(self.fake, conversation), [[conversation, "new"]])

    def assertLeftDead(self, name):
        """Its pane dead, and nothing drawn over it: what ak did about the end went elsewhere."""
        self.assertStaysDown(name)
        self.assertEqual(says(self.home, name, "#{pane_dead}\t#{pane_in_mode}"), "1\t0")

    def test_a_harness_that_exits_0_comes_back_in_its_pane_on_its_conversation(self):
        self.assertBackOnItsConversation("quit")

    def test_a_harness_killed_by_a_signal_comes_back_the_same_way(self):
        self.assertBackOnItsConversation("crash")

    def test_a_seat_stopped_with_ak_orch_stop_stays_gone(self):
        self.assertStaysDown("stopped")
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=stopped").code, 0)

    def test_a_seat_the_owner_closed_stays_down_when_its_harness_ends(self):
        self.assertLeftDead("closed")

    def test_a_harness_that_ends_inside_its_warm_up_stays_down_saying_how_to_open_it(self):
        self.assertLeftDead("early")
        shown = self.home.tmux("capture-pane", "-p", "-t", "=early:").out
        lines = [line for line in shown.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, shown)
        self.assertIn("Ctrl-b m", lines[0])
        self.assertIn("number", lines[0])


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AServerStartedWithoutIt(unittest.TestCase):
    def test_gets_it_from_the_tick_and_its_harness_that_exits_0_comes_back(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            fake = fakeadapter.install(home, claude="pass")["claude"]
            fake.answer("interactive", TUI, given=(CONVERSATION,))
            # a seat as an ak before this change left it, on a server started without the hook
            seat = Seat(home, "acme", record={"conversation": CONVERSATION})
            opened_on_its_own(home, "acme", seat.cwd)
            ticked = home.tick()
            self.assertEqual(ticked.code, 0, ticked.out + ticked.err)
            # in its place a harness that quits at Enter, as at the owner's `/exit`, past any
            # warm-up: its record holds no launch
            done = home.tmux("respawn-pane", "-k", "-t", seat.pane, TUI)
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(home.tmux("send-keys", "-t", seat.pane, "Enter").code, 0)
            wait(lambda: launches(fake, CONVERSATION) == [[CONVERSATION]]
                 and says(home, "acme", "#{pane_dead}") == "0", "acme never came back")
            self.assertEqual(says(home, "acme", "#{pane_id}\t#{@ak_harness_pane}"),
                             f"{seat.pane}\t{seat.pane}")


if __name__ == "__main__":
    unittest.main()
