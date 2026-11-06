"""A seat working its own turn after its usage came back reads `working`, however often its
screen redraws.

A seat refused for usage waits, and reads `out of usage` whatever its screen shows; a turn of its
own, begun after the wait on an account with room, ends that wait.  Seen on 5 Nov 2026: a working
Claude Code redraws its spinner's timer every second, a tick took that for the owner acting during
its slow meter reading and left the wait standing, and the seat read `out of usage` for five
minutes while it worked.  Black-box: the program `AK_BIN` names runs `ak watch` from outside
through tests/fixtures/akbin.py, beside a seat of tests/fixtures/akseat.py whose turn's start is
fired as Claude fires it (tests/fixtures/hookdrive.py), on the usage readings the test writes.
"""

import json
import re
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
WORKING = (FIXTURES / "claude-working-pane.txt").read_text(encoding="utf-8")
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "message": {
    "role": "assistant", "content": [{"type": "text", "text":
                                      "You've hit your 5-hour limit · resets 6:59pm"}]}}


def spinner(seconds):
    """Claude Code's working screen, its spinner at `seconds` into the turn."""
    glyph = "·✢✳✶✻✽"[seconds % 6]
    return WORKING.replace("✶ Baking…", f"{glyph} Baking… ({seconds}s · ↓ {seconds * 7} tokens)")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class SeatWorkingAfterItsUsageCameBack(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["opus"])
        fakeadapter.install(home, claude="pass")

    def redrawn(self, seat):
        """The seat's pane drawing a new spinner frame ten times a second until the test ends."""
        stop = threading.Event()

        def draw():
            frame = 0
            while not stop.wait(0.1):
                frame += 1
                swap = seat.screen_file.with_suffix(".swap")
                swap.write_text(spinner(frame), encoding="utf-8")
                swap.replace(seat.screen_file)
        drawing = threading.Thread(target=draw)
        drawing.start()
        self.addCleanup(drawing.join)
        self.addCleanup(stop.set)

    def word(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        return why.out.splitlines()[0].split(None, 1)[1]

    def test_its_own_turn_on_an_account_with_room_reads_working(self):
        now = time.time()
        seat = Seat(self.home, "acme", screen=spinner(0), planned=True)
        # refused ten minutes ago, with the wait ak recorded then
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.home.write(f".claude/projects/{folder}/conv-acme.jsonl", "".join(
            json.dumps(line) + "\n" for line in
            ({"type": "user", "message": {"role": "user", "content": "go"}}, REFUSED)))
        self.home.write(".agentkit/state/seat-acme.json", {
            "session": "acme", "usage_wait": {
                "reason": "anthropic out of usage until 18:59", "since": now - 600,
                "until": now + 3600, "continue": False}})
        # its account came back, and a line typed into it began a turn of its own
        meters = {"provider": "anthropic", "resets": 0, "meters": [
            {"name": "session", "used": 10, "window_secs": 18000, "resets_at": now + 10800},
            {"name": "weekly_all", "used": 30, "window_secs": 604800,
             "resets_at": now + 3 * 86400}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": meters}})
        fired = Hooks(self.home).prompt("the run you waited on ended", seat)
        self.assertEqual(fired.code, 0, fired)
        self.assertEqual(self.word(), "out of usage")
        self.redrawn(seat)
        words = []
        for _ in range(3):
            done = self.home.ak("watch", boxed=True)
            self.assertEqual(done.code, 0, done.out + done.err)
            words.append(self.word())
        self.assertEqual(words[-1], "working", words)
        self.assertEqual(seat.lines(), [])      # nothing typed into its turn


if __name__ == "__main__":
    unittest.main()
