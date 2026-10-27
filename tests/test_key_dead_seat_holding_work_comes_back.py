"""A seat whose harness died idle while it held background work is reopened and told what it held.

On 27 Oct 2026 Codex, Antigravity and Claude seats were each killed holding background work and
stayed closed, and the one the owner reopened was told nothing of it.  The owner decided such a
seat comes back on its own conversation, told what it held, as a mid-turn seat does, on every
tick and after a reboot alike.  A watch is not work: a seat holding only a monitor, or nothing,
stays closed.  Black-box: the program `AK_BIN` names runs `ak watch` from outside through
tests/fixtures/akbin.py, beside seats of tests/fixtures/akseat.py whose hooks are fired as Claude
fires them (tests/fixtures/hookdrive.py), each reopened by a scripted harness of fakeadapter.py.
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
SHELL = {"id": "b1", "type": "shell", "status": "running", "description": "sleep 600"}
TERMINAL = {"id": "t1", "type": "terminal", "status": "running", "description": "npm run dev"}
MONITOR = {"id": "m1", "type": "monitor", "status": "running", "description": "watch ci"}
HELD = "background work: {}"
BOOT_FILE = Path("/proc/sys/kernel/random/boot_id")


def conversation(n):
    return f"0b9c6f4e-1d2a-4c3b-8e5f-6a7b8c9d0e2{n}"


def dead(home, name):
    return home.tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").out.strip()


def seats(home, held):
    """A Home with one seat per name in `held`, each having ended its turn on a Stop listing
    that background work, and the fake harness that reopens them."""
    with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
        probe.bind(("127.0.0.1", 0))
        home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                        GIT_ALLOW_PROTOCOL="file")
    akconfig.write(home, ["opus"])
    fake = fakeadapter.install(home, claude="pass")["claude"]
    hooks, made = Hooks(home), {}
    for n, (name, work) in enumerate(held.items()):
        seat = made[name] = Seat(home, name, record={"conversation": conversation(n)})
        # Claude files a workspace's conversations under its path, each character that is not
        # a letter or a digit a dash: this one it has opened, so it is resumed.
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/{conversation(n)}.jsonl",
                   '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        fake.answer("interactive", shlex.join([sys.executable, str(PANE),
                                               str(seat.screen_file), str(seat.typed_file)]),
                    given=(conversation(n),))
        for event, payload in (("UserPromptSubmit", {"prompt": "go"}),
                               ("Stop", {"background_tasks": work, "transcript_path": "",
                                         "last_assistant_message": "Started it."})):
            fired = hooks.fire(event, payload, seat=name, pane=seat)
            assert fired.code == 0, fired
    return fake, made


def opened(fake):
    """The conversation and first prompt of each relaunch the harness was handed."""
    return {call["argv"][-1]: call["env"].get("AGENTKIT_FIRST_PROMPT")
            for call in fake.calls("interactive")}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class DeadSeatHoldingWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.fake, cls.seats = seats(home, {"shell": [SHELL], "monitor": [MONITOR],
                                           "nothing": []})
        for name in cls.seats:
            done = home.tmux("respawn-pane", "-k", "-t", f"={name}:", "true")
            assert done.code == 0, done.err
            deadline = time.monotonic() + 30
            while dead(home, name) != "1":
                assert time.monotonic() < deadline, f"{name}'s pane never died"
                time.sleep(0.05)
        cls.tick = home.ak("watch", boxed=True)
        cls.after = {name: dead(home, name) for name in cls.seats}
        cls.opened = opened(cls.fake)

    def test_the_tick_exits_zero(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)

    def test_a_seat_that_died_idle_holding_a_shell_comes_back_told_what_it_held(self):
        self.assertEqual(self.after["shell"], "0")
        self.assertIn(conversation(0), self.opened)
        told = self.opened[conversation(0)] or self.seats["shell"].wait_lines(1)[0]
        self.assertIn(HELD.format("shell"), told)

    def test_a_seat_holding_only_a_monitor_or_nothing_stays_closed(self):
        for n, name in ((1, "monitor"), (2, "nothing")):
            self.assertEqual(self.after[name], "1", name)
            self.assertNotIn(conversation(n), self.opened, name)
            self.assertEqual(self.seats[name].lines(), [], name)


@unittest.skipUnless(REAL_TMUX and boxable() and BOOT_FILE.is_file(),
                     "no tmux, no bwrap able to box a tick here, or no kernel boot id")
class RebootedSeatHoldingWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.fake, cls.seats = seats(home, {"terminal": [TERMINAL], "nothing": []})
        # the owner's own session keeps ak's tmux server up once the reboot took the seats'
        kept = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "notes", "sleep 600")
        assert kept.code == 0, kept.err
        for name in cls.seats:
            home.tmux("kill-session", "-t", f"={name}")
        state = home.path / ".agentkit/state/watch.json"
        home.write(".agentkit/state/watch.json", {
            **(json.loads(state.read_text()) if state.is_file() else {}), "boot_id": "before"})
        cls.tick = home.ak("watch", boxed=True)
        cls.opened = opened(cls.fake)

    def test_the_tick_exits_zero(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)

    def test_a_seat_that_held_a_terminal_comes_back_told_what_it_held(self):
        self.assertIn(HELD.format("terminal"), self.opened.get(conversation(0)) or "")

    def test_a_seat_holding_nothing_stays_closed(self):
        self.assertNotIn(conversation(1), self.opened)


if __name__ == "__main__":
    unittest.main()
