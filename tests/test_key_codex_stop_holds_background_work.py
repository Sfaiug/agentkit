"""A Codex seat's Stop names the background work it still has in flight, as a Claude seat's does.

A seat's harness ending ends its background work with it.  So each Stop records what the seat
holds, the type of each piece (`holds`), and a seat holding work leaves an account with usage
left only once it is spent (tests/test_key_background_work_holds_the_account.py).  A Codex seat
holds its background terminals and the sub-agents it spawned that still work.  Codex wakes it
for neither once it ends, so its Stop still reads as a stop.

Black-box: the program `AK_BIN` names opens a Codex seat from a person's terminal
(tests/fixtures/akterm.py).  Its `codex` is tests/fixtures/codex-remote-fake.py, Codex's app
server and remote TUI, which fires the seat's Stop from its own server as Codex does, and
answers the server's listings with what this test writes.  Those answers are shaped as the
schema Codex 0.163.0 generates for its app server (`codex app-server generate-json-schema`)
says: ThreadBackgroundTerminalsListResponse, and ThreadListResponse with its Thread and
ThreadStatus.  The tick meets usage readings the test writes, and no provider.
"""

import json
import os
import shlex
import signal
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, REPO, Home, boxable
from fixtures.akseat import FIXTURES
from fixtures.akterm import Terminal

THREAD = "01a17700-0000-7000-8000-00000000acme"
NONE = {"data": [], "nextCursor": None}
TERMINAL = {"itemId": "exec-acme-1", "processId": "41", "osPid": 4141, "command": "npm run dev",
            "cwd": "/code/acme", "cpuPercent": 0.5, "rssKb": 2048}


def agent(name, status):
    """A thread the seat's thread spawned, as thread/list returns one."""
    return {"id": f"01a17700-0000-7000-8000-0000000{name}", "sessionId": THREAD,
            "parentThreadId": THREAD, "agentNickname": name, "agentRole": None,
            "preview": "Check the api", "cwd": "/code/acme", "cliVersion": "0.163.0",
            "createdAt": 1793000000, "updatedAt": 1793000000, "ephemeral": False,
            "modelProvider": "openai", "projectId": None, "turns": [], "status": status,
            "source": {"subAgent": {"thread_spawn": {"parent_thread_id": THREAD, "depth": 1}}}}


def until(test, what, bound=60):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CodexStopHoldsBackgroundWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: no provider is reached
            probe.bind(("127.0.0.1", 0))
            dead = f"http://127.0.0.1:{probe.getsockname()[1]}"
        home.env.update({"FAKE_CODEX_REPO": str(REPO), "FAKE_THREAD": THREAD, "FAKE_HOLD": "1",
                         "FAKE_SCREEN": str(FIXTURES / "codex-prompt-pane.txt"),
                         "https_proxy": dead, "HTTPS_PROXY": dead, "GIT_ALLOW_PROTOCOL": "file"})
        home.fake("codex", "#!/bin/sh\nexec " + shlex.join(
            [sys.executable, str(FIXTURES / "codex-remote-fake.py")]) + ' "$@"\n')
        for login in (".codex", ".codex-second"):      # each account's, where Codex keeps it
            home.write(f"{login}/auth.json", {"tokens": {"access_token": "acme-token",
                                                         "account_id": "acme-account"}})
        akconfig.write(home, ["astra"], providers={"openai": {"accounts": ["default", "second"]}})
        cls.terminal = Terminal(home, "orch", "acme", "--model", "astra", "--workers", "astra")
        until(lambda: list(home.path.rglob("fake-tui.json")), "saw the Codex seat open")
        server, = home.path.rglob("fake-server.json")
        cls.server = json.loads(server.read_text())["pid"]

    def stop(self, terminals, threads):
        """The seat's turn ends with that in flight: its Stop as ak writes it down."""
        self.home.write("in-flight.json", {"thread/backgroundTerminals/list": terminals,
                                           "thread/list": threads})
        fact = self.home.path / ".agentkit/state/hook-acme.json"
        before = json.loads(fact.read_text())["at"]
        os.kill(self.server, signal.SIGUSR1)
        until(lambda: json.loads(fact.read_text())["at"] > before, "saw the Stop written down")
        stopped = json.loads(fact.read_text())
        self.assertEqual((stopped["event"], stopped["kind"]), ("Stop", ""))   # no wait
        return stopped

    def tick(self, used=97):
        """One tick with the seat's account `used`% into its 5h window and the other at 10%, its
        terminal untouched for ten minutes: the account it is on after."""
        now = time.time()

        def reading(used):
            return {"provider": "openai", "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
                {"name": "weekly_all", "used": 30, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"openai": {
                **reading(used), "accounts": {"default": reading(used), "second": reading(10)}}}})
        tty = self.home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_tty}").out.strip()
        os.utime(tty, (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        return record.get("account") or "default"

    def test_1_a_stop_holding_a_terminal_and_a_sub_agent_names_both(self):
        held = self.stop({"data": [TERMINAL], "nextCursor": None},
                         {"data": [agent("ada", {"type": "active", "activeFlags": []}),
                                   agent("bo", {"type": "idle"})], "nextCursor": None})
        self.assertEqual(held["holds"], ["terminal", "agent"])

    def test_2_a_stop_with_nothing_in_flight_holds_nothing(self):
        self.assertNotIn("holds", self.stop(NONE, NONE))

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_3_a_seat_holding_work_stays_on_an_account_with_usage_left(self):
        # a first tick names the new seat's thread, typing into it: a seat typed into stays
        self.assertEqual(self.tick(used=10), "default")
        self.stop({"data": [TERMINAL], "nextCursor": None}, NONE)
        self.assertEqual(self.tick(), "default")
        self.stop(NONE, NONE)
        self.assertEqual(self.tick(), "second")


if __name__ == "__main__":
    unittest.main()
