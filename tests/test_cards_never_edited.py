"""A card goes out once, its emoji first, and is never edited: the owner has read it by the time
he answers, so his mention stays and nothing turns it `Answered` or `Done` (owner, 19 Oct
2026).  A question over before Discord took its card never goes out late.

Offline: temporary seat state and a local webhook.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, notify, orch, watch

SEAT = "fix-api"


class CardsNeverEdited(Sandbox):
    def setUp(self):
        super().setUp()
        self.now, self.requests, self.down = 10000, [], False
        owner = self

        class Webhook(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status = 503 if owner.down else 200
                owner.requests.append((self.command, body.get("content"), status))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": str(len(owner.requests))}).encode())

            do_PATCH = do_POST

        server = ThreadingHTTPServer(("127.0.0.1", 0), Webhook)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.stack.enter_context(patch.dict(os.environ, {
            notify.SINK_ENV: f"http://127.0.0.1:{server.server_port}/hook",
            "AGENTKIT_DISCORD_USER_ID": "", "AK_RUN_ROLE": "", "AGENTKIT_SESSION": ""}))
        self.stack.enter_context(patch.object(notify.time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "session_state",
                                              side_effect=lambda *_a, **_k: dict(self.word)))
        config.save_session(self.cfg, SEAT, "opus", ["opus"], {"cwd": str(self.root)})

    def says(self, word, since, after=0):
        """A tick `after` seconds into the seat reading `word` since `since`."""
        self.now, self.word = since + after, {"word": word, "reason": "", "since": since}
        self.assertEqual(notify.transition(SEAT), 0)

    def test_a_card_carries_its_emoji_and_stays_as_it_went(self):
        self.says("needs you", 10000)
        self.says("needs you", 10000, after=notify.CARD_WAIT)
        notify.answered(SEAT, self.now + 1)                 # his prompt
        self.says("needs you", 10000, after=notify.CARD_WAIT + 2)
        self.says("working", 10100)
        notify.record(SEAT, "done", "Shipped the parser", time=10200)
        self.says("done", 10200)
        notify.forget_card(SEAT)                            # and the seat goes
        self.assertEqual(self.requests, [("POST", f"\U0001f64b Needs you · {SEAT}", 200),
                                         ("POST", f"✅ Done · {SEAT}", 200)])

    def asked_while_discord_was_down(self):
        self.down = True
        self.says("needs you", 10000, after=notify.CARD_WAIT)
        self.down, self.now = False, self.now + 100000      # and every retry is due

    def late(self):
        """The tick's card pass, then its retries, in the tick's own order: what Discord got."""
        wanted = ("the card transition pass did not run", "the notification retry did not run")
        with patch.object(orch, "listing", return_value=[{"name": SEAT}]):
            for what, step, _ in watch.local_passes({}, False, lambda _line: None):
                if what in wanted:
                    step()
        return [request[2] for request in self.requests]

    def test_a_standing_question_goes_out_late_once(self):
        self.asked_while_discord_was_down()
        self.assertEqual(self.late(), [503, 200])
        self.assertEqual(self.late(), [503, 200])

    def test_an_answered_question_never_goes_out_late(self):
        self.asked_while_discord_was_down()
        notify.answered(SEAT, self.now)
        self.assertEqual(self.late(), [503])

    def test_a_question_the_seat_moved_on_from_never_goes_out_late(self):
        """A dialog granted between two ticks: the card pass reads it before any retry."""
        self.asked_while_discord_was_down()
        self.word = {"word": "working", "reason": "", "since": self.now}
        self.assertEqual(self.late(), [503])

    def test_a_gone_seats_question_never_goes_out_late(self):
        self.asked_while_discord_was_down()
        notify.forget_card(SEAT)
        notify.retry_pending(log=lambda _line: None)
        self.assertEqual([request[2] for request in self.requests], [503])


if __name__ == "__main__":
    unittest.main()
