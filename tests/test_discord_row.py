"""The `c` screen's Discord row names who a card pings and which webhook it goes to. Offline.

The name is learned from Discord itself, with no bot: a delivered card's receipt, the created
message, carries the mentioned user in `mentions`. A local webhook answers the way Discord does,
and $AK_NOTIFY_SINK points at it, so nothing here can reach the owner's Discord; the configured
webhook is that same local one, so nothing is diverted either. A temporary HOME holds the config,
the secrets and the state.
"""

from contextlib import ExitStack, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, terminal, update

USER = "123456789012345678"


class DiscordRow(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".discord-row-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.requests = []
        owner = self

        class Hook(BaseHTTPRequestHandler):
            """Discord's answer to `?wait=true`: the message, with the users it mentions."""

            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append((self.path, data))
                mentions = [{"id": found, "username": "acme-owner", "global_name": "Acme"}
                            for found in re.findall(r"<@(\d+)>", data.get("content", ""))]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": "77", "mentions": mentions}).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}/api/webhooks/42/"
        self.url = self.base + "tokena1B2c3"
        env = {key: value for key, value in os.environ.items()
               if key not in ("AGENTKIT_DISCORD_WEBHOOK", "AGENTKIT_DISCORD_USER_ID")}
        env.update({"HOME": str(self.home), notify.SINK_ENV: self.url, "NO_COLOR": "1",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        self.stack.enter_context(patch.object(config, "HOME", self.home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.home / name.lower()))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        (self.home / "config.toml").write_text((REPO / "config.default.toml").read_text())
        config.ensure_dirs()
        for name, value in (("discord_webhook", self.url), ("discord_user_id", USER)):
            (config.SECRETS / name).write_text(value + "\n")

    def row(self):
        """The Discord row's value, as the `c` screen draws it."""
        lines, _ = menu.config_body(config.load(), "abc1234")
        return next(re.fullmatch(r"  Discord +(.*)", line).group(1) for line in lines
                    if line.startswith("  Discord "))

    def page(self, *answers):
        """The Discord page against typed `answers`; the line it shows over its questions."""
        out = io.StringIO()
        with patch.object(menu, "read", side_effect=list(answers)), redirect_stdout(out):
            menu.config_discord()
        return [line.strip() for line in out.getvalue().splitlines() if "webhook" in line]

    def deliver(self):
        receipt = {}
        payload = {"username": "agentkit", "content": notify.mention(),
                   "embeds": [notify.embed("needs", "seat", "Merge?")]}
        self.assertEqual(notify.post(payload, [], "Merge?", receipt), 0)
        self.assertEqual(receipt["status"], "delivered")

    def test_the_name_is_learned_from_a_receipt_and_drawn_with_the_webhook_tail(self):
        self.assertEqual(self.row(), "id …5678 · webhook …a1B2c3")   # no card delivered yet
        self.deliver()
        self.assertEqual(self.requests[0][0], "/api/webhooks/42/tokena1B2c3?wait=true")
        self.assertEqual(self.requests[0][1]["content"], f"<@{USER}>")
        self.assertEqual(self.row(), "@acme-owner · webhook …a1B2c3")
        self.assertEqual(self.page("q"), ["@acme-owner · webhook …a1B2c3"])
        state = "".join(path.read_text() for path in config.STATE.rglob("*") if path.is_file())
        self.assertIn("acme-owner", state)
        self.assertNotIn("a1B2c3", state)            # none of the URL is kept, not even its tail

    def test_changing_the_secrets_on_the_page_changes_the_row_at_once(self):
        self.deliver()
        self.page("", "987654321098765432")            # another user: not the one named
        self.assertEqual(self.row(), "id …5432 · webhook …a1B2c3")
        self.page(self.base + "tokenZ9y8x7", USER)    # the named user again, a new webhook
        self.assertEqual(self.row(), "@acme-owner · webhook …Z9y8x7")
        self.assertEqual(len(self.requests), 1)       # setting the secrets posts nothing

    def test_no_webhook_is_not_connected_and_no_user_id_names_no_one(self):
        (config.SECRETS / "discord_user_id").unlink()
        self.assertEqual(self.row(), "webhook …a1B2c3")
        (config.SECRETS / "discord_webhook").unlink()
        self.assertEqual(self.row(), "not connected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
