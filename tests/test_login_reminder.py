"""A login ending within 3 days pages the owner once a day.

The tick's login pass on a temporary HOME, with a fake adapter, a clock the test sets, local
time five hours behind UTC so a local day is not UTC's, and $AK_NOTIFY_SINK on a loopback
server that keeps what Discord would have been sent, or refuses it as a Discord that is down.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, watch

ADAPTER = r"""#!/usr/bin/env bash
[ "$1" = login-end ] || exit 2
cat "$FAKE/answer-${AGENTKIT_ACCOUNT:-default}"
"""


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.server.refuse:
            self.server.refuse -= 1
            self.send_response(503)
        else:
            self.server.posts.append(body)
            self.send_response(204)
        self.end_headers()

    def log_message(self, *_):
        pass


def local(day, hour, minute=0):
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


class Reminder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.fake, adapters = root / "fake", root / "adapters"
        self.fake.mkdir()
        adapters.mkdir()
        (adapters / "claude.sh").write_text(ADAPTER)
        (adapters / "claude.sh").chmod(0o755)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            patcher = patch.object(config, name, root / name.lower())
            patcher.start()
            self.addCleanup(patcher.stop)
        sink = HTTPServer(("127.0.0.1", 0), Sink)
        sink.posts = self.posts = []
        sink.refuse = 0
        self.sink = sink
        threading.Thread(target=sink.serve_forever, daemon=True).start()
        self.addCleanup(sink.server_close)
        self.addCleanup(sink.shutdown)
        self.addCleanup(time.tzset)
        env = patch.dict(os.environ, {
            "FAKE": str(self.fake), config.ADAPTER_DIR_ENV: str(adapters), "TZ": "EST+5",
            "AK_NOTIFY_SINK": f"http://127.0.0.1:{sink.server_port}/hook",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        time.tzset()
        self.cfg = {"providers": {"anthropic": {"accounts": ["default", "second"]}},
                    "models": {"opus": {"harness": "claude", "provider": "anthropic"}}}
        self.answer("default", None)
        self.answer("second", local(26, 4, 47))

    def answer(self, account, ends):
        (self.fake / f"answer-{account}").write_text(
            json.dumps({"email": f"{account}@acme.test", "ends": ends}))

    def tick(self, at):
        passes = {what: run for what, run, _ in watch.local_passes({}, False, print)}
        with patch.object(config, "load", return_value=self.cfg), \
                patch.object(time, "time", return_value=at):
            passes["the notification retry did not run"]()
            passes["the login-end read did not run"]()
        return [post["content"] for post in self.posts]

    def test_a_one_page_a_local_day_naming_the_subscription_and_nothing_else(self):
        said = "🙋 Needs you · Claude II login"
        self.assertEqual(self.tick(local(24, 10)), [said])
        self.assertEqual(self.tick(local(24, 23, 30)), [said])     # Sunday already, in UTC
        self.assertEqual(self.tick(local(25, 0, 30)), [said] * 2)
        self.assertEqual(self.tick(local(27, 9)), [said] * 3)

    def test_b_four_days_away_no_end_or_renewed_pages_nothing(self):
        self.answer("second", local(28, 10, 1))
        self.assertEqual(self.tick(local(24, 10)), [])
        self.answer("second", local(26, 4, 47))
        self.assertEqual(len(self.tick(local(25, 10))), 1)
        self.answer("second", local(26, 4, 47) + 30 * 86400)
        self.assertEqual(len(self.tick(local(26, 10))), 1)

    def test_c_a_page_not_taken_is_retried_while_due_and_never_once_renewed(self):
        self.sink.refuse = 1
        self.assertEqual(self.tick(local(24, 10)), [])
        self.assertEqual(len(self.tick(local(24, 10, 2))), 1)     # its minute's retry
        self.sink.refuse = 1
        self.assertEqual(len(self.tick(local(25, 10))), 1)
        self.answer("second", local(26, 4, 47) + 30 * 86400)
        self.assertEqual(len(self.tick(local(25, 11, 1))), 1)     # asked again: renewed
        self.assertEqual(len(self.tick(local(25, 12))), 1)

    def test_d_a_page_not_taken_before_this_install_is_never_sent_after_it(self):
        self.sink.refuse = 1
        self.assertEqual(self.tick(local(24, 10)), [])
        (config.STATE / "installed-at").write_text(str(local(24, 10, 1)))
        self.assertEqual(self.tick(local(24, 10, 2)), [])


if __name__ == "__main__":
    unittest.main()
