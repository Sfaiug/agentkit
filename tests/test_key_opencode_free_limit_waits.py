"""An OpenCode seat out of today's free messages reads `out of usage` until they reset, and
nothing is typed into it before then.

Seen on 30 Oct 2026 with OpenCode 2.2.3: the session's last `idle` row in opencode.db held a
`provider.free-limit` error, 429, with `retryAfterMs` counted from that row's own time, and the
screen said when the free messages reset, in a box whose shading it keeps redrawing.
That is a spent window with a known reset, not a bare rate limit to type `continue` past.
Black-box: `AK_BIN` ticks beside an akseat.py seat on that screen, whose session ends on such a
row, shaped as OpenCode 2.2.3 left it, under invented ids; the tick meets usage readings the test
writes, and no provider.
"""

import itertools
import json
import os
import socket
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat

TOKEN, SESSION = "c" * 32, "ses_0fa1c2d3e4ffAcmeFreeLimit"
RETRY_MS = 38_272_000
LIMIT = "You've used today's free messages. They reset at 1:22 AM · 10/31/2026."
FREE = ("Free usage limit reached. Connect a provider or subscribe to OpenCode Go to keep going,"
        " or switch models.")
MESSAGES = """CREATE TABLE `session_message` (
          `id` text PRIMARY KEY,
          `session_id` text NOT NULL,
          `type` text NOT NULL,
          `seq` integer NOT NULL,
          `time_created` integer NOT NULL,
          `time_updated` integer NOT NULL,
          `data` text NOT NULL
        )"""


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class OpencodeFreeLimitWaits(unittest.TestCase):
    def test_the_seat_reads_out_of_usage_while_its_limit_screen_redraws(self):
        home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: no provider is reached
            probe.bind(("127.0.0.1", 0))
            dead = f"http://127.0.0.1:{probe.getsockname()[1]}"
        home.env.update(https_proxy=dead, HTTPS_PROXY=dead)
        akconfig.write(home, {"flash": {"harness": "opencode", "provider": "opencode",
                                        "model": "opencode/deepseek-v4.1-flash-free"}})
        now = time.time()
        failed = int(now * 1000) - 60_000
        error = {"type": "provider.free-limit", "status": 429, "message": FREE,
                 "retryAfterMs": RETRY_MS}
        db = home.path / ".local/share/opencode/opencode.db"
        db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(MESSAGES)
            for seq, (kind, data) in enumerate([
                    ("user", {"text": "Rename the acme report."}),
                    ("assistant", {"content": [], "finish": "error", "error": error}),
                    ("idle", {"outcome": "failed", "error": error})]):
                at = failed - 2 + seq
                conn.execute("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (f"msg_0fa1c2d3e4ffFree{seq}", SESSION, kind, seq, at, at,
                              json.dumps({"time": {"created": at}, **data})))
        home.write(f".agentkit/state/opencode-launch-{TOKEN}/session", SESSION)
        screen = (FIXTURES / "opencode-stall-pane.txt").read_text().replace(
            "Error: 429 Too Many Requests", LIMIT)
        seat = Seat(home, "acme", model="flash", screen=screen,
                    record={"opencode_launch": TOKEN, "launched": now - 600})
        home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now,
            "providers": {"opencode": {"provider": "opencode", "meters": [], "resets": 0}}})
        tty = home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_tty}").out.strip()
        os.utime(tty, (now - 600, now - 600))
        # OpenCode redraws the box frame after frame, only its shading changing; here each frame
        # has a shade of its own, written to the pane's terminal faster than a tick looks twice.
        lines = screen.split("\n")
        y = next(at for at, line in enumerate(lines) if LIMIT in line)
        cursor = f"\x1b[{y + 1};{lines[y].index(LIMIT) + 1}H"
        stop = threading.Event()

        def redraw():
            with open(tty, "w", encoding="utf-8") as terminal:
                for n in itertools.count():
                    if stop.wait(0.001):
                        return
                    terminal.write(f"\x1b7{cursor}\x1b[48;2;{n >> 16 & 255};{n >> 8 & 255};"
                                   f"{n & 255}m{LIMIT}\x1b[0m\x1b8")
                    terminal.flush()

        drawing = threading.Thread(target=redraw)
        drawing.start()
        self.addCleanup(drawing.join)
        self.addCleanup(stop.set)
        reset = time.strftime("%Y-%m-%d %H:%M", time.gmtime(failed / 1000 + RETRY_MS / 1000))
        for tick in range(2):
            with self.subTest(tick=tick):
                done = home.ak("watch", boxed=True)
                self.assertEqual(done.code, 0, done.out + done.err)
                listed = home.ak("orch", "list", env={"COLUMNS": "200"})
                self.assertEqual(listed.code, 0, listed.err)
                row, = (line for line in listed.out.splitlines() if line.startswith("acme "))
                self.assertIn("out of usage", row)
                why = home.ak("orch", "why", "acme")
                self.assertEqual(why.code, 0, why.err)
                self.assertIn(f"opencode out of usage until {reset}", why.out)
                self.assertEqual(seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
