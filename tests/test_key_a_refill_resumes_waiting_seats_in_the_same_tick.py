"""The tick whose usage refresh reads room again resumes, in that same tick, the seats that
waited for it.

A seat refused for usage waits for its subscription to have room again.  Seen on 12 Nov 2026:
the reading that showed room came at 08:24 and the runs waiting on it went on at 08:24, but the
seats only at 08:30, a tick later, as the tick looked at its seats before it read usage.  The
owner: "WHen we have usage again, sessions should start by themselves."  Black-box: the program
`AK_BIN` names runs `ak watch` from outside through tests/fixtures/akbin.py, beside a seat of
tests/fixtures/akseat.py on a fake Claude harness (tests/fixtures/fakeadapter.py) whose `usage`
answers room; the snapshot it read before says spent, and Claude's adapter was last asked an
hour ago, so this tick asks it again.
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

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "apiError": "usage_limit_reached",
           "message": {"role": "assistant", "content": [
               {"type": "text", "text": "Back after a little rest"}]}}


def reading(now, used):
    """Anthropic's meters, its five hours `used`% spent."""
    return {"meters": [
        {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
        {"name": "weekly_all", "used": 30, "window_secs": 604800, "resets_at": now + 3 * 86400}]}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class RefillResumesWaitingSeatsInTheSameTick(unittest.TestCase):
    def test_the_tick_reading_room_again_restarts_the_waiting_seat_and_tells_it_to_go_on(self):
        home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["opus"])
        claude = fakeadapter.install(home, claude="pass")["claude"]
        now = time.time()
        claude.answer("usage", json.dumps({**reading(now, 10), "error": None}))
        # refused ten minutes ago, its plan still open, with the wait ak recorded then
        seat = Seat(home, "acme", planned=True)
        claude.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/conv-acme.jsonl", "".join(
            json.dumps(line) + "\n" for line in
            ({"type": "user", "message": {"role": "user", "content": "go"}}, REFUSED)))
        home.write(".agentkit/state/seat-acme.json", {"session": "acme", "usage_wait": {
            "reason": "anthropic out of usage", "since": now - 600, "until": now + 10800,
            "continue": True}})
        # spent, as the snapshot assembled a minute ago read it; its adapter last asked an hour ago
        home.write(".agentkit/state/usage.json", {
            "fetched_at": now - 60, "reset_checked_at": now, "providers": {
                "anthropic": {"provider": "anthropic", "resets": 0, "probed_at": now - 3600,
                              **reading(now, 100)}}})
        home.write(".agentkit/state/anthropic-probe.lock", repr(now - 3600))
        done = home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("usage", [call["verb"] for call in claude.calls()], "the tick never asked")
        told = [call["env"].get("AGENTKIT_FIRST_PROMPT") for call in claude.calls("interactive")]
        self.assertEqual(len(told), 1, f"restarted {len(told)} times")
        self.assertTrue(told[0], "restarted, told nothing to go on with")


if __name__ == "__main__":
    unittest.main()
