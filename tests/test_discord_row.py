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
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, terminal, update
from agentkit.terminal import Key

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
        lines, _ = menu.config_body(config.load())
        return next(re.fullmatch(r"  Discord +(.*)", line).group(1) for line in lines
                    if line.startswith("  Discord "))

    def page(self, *typed):
        """The Discord page with each of `typed` typed under its row in turn, a row down from
        the one before, then Esc; its rows as it drew them last, the highlight's mark aside."""
        keys = [key for number, text in enumerate(typed) for key in (
            *[Key("down")] * bool(number), Key("enter"), *(Key("char", c) for c in text),
            Key("enter"))]
        out = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=[*keys, Key("esc")]), \
                redirect_stdout(out):
            menu.config_discord()
        last = terminal.ANSI.sub("", out.getvalue()).split("agentkit · config · discord")[-1]
        return [" ".join(line[1:].split()) for line in last.splitlines()
                if line[2:].startswith(("Mention", "Webhook"))]

    def deliver(self):
        receipt = {}
        self.assertEqual(notify.post(notify.card_payload("needs", "seat"), [], "Merge?",
                                     receipt), 0)
        self.assertEqual(receipt["status"], "delivered")

    def test_the_name_is_learned_from_a_receipt_and_drawn_with_the_webhook_tail(self):
        self.assertEqual(self.row(), "id …5678 · webhook …a1B2c3")   # no card delivered yet
        self.deliver()
        self.assertEqual(self.requests[0][0], "/api/webhooks/42/tokena1B2c3?wait=true")
        self.assertEqual(self.requests[0][1]["content"], f"🙋 Needs you · seat <@{USER}>")
        self.assertEqual(self.row(), "@acme-owner · webhook …a1B2c3")
        self.assertEqual(self.page(), ["Mention @acme-owner", "Webhook …a1B2c3"])
        state = "".join(path.read_text() for path in config.STATE.rglob("*") if path.is_file())
        self.assertIn("acme-owner", state)
        self.assertNotIn("a1B2c3", state)            # none of the URL is kept, not even its tail

    def test_changing_the_secrets_on_the_page_changes_the_row_at_once(self):
        self.deliver()
        # another user: not the one named; the page says so at once, as the row does
        self.assertEqual(self.page("987654321098765432"),
                         ["Mention id …5432", "Webhook …a1B2c3"])
        self.assertEqual(self.row(), "id …5432 · webhook …a1B2c3")
        self.page(USER, self.base + "tokenZ9y8x7")    # the named user again, a new webhook
        self.assertEqual(self.row(), "@acme-owner · webhook …Z9y8x7")
        for name in ("discord_webhook", "discord_user_id"):    # written as install.sh writes them
            self.assertEqual(stat.S_IMODE((config.SECRETS / name).stat().st_mode), 0o600)
        self.page("", "")                             # Enter with nothing typed keeps both
        self.assertEqual(self.row(), "@acme-owner · webhook …Z9y8x7")
        self.page("@acme-owner")                      # a name is no user id: refused
        self.assertEqual((config.SECRETS / "discord_user_id").read_text(), USER + "\n")
        self.assertEqual(len(self.requests), 1)       # setting the secrets posts nothing

    def test_a_field_opened_on_a_short_screen_stays_on_it(self):
        frames, rows = [], []

        def frame(title, body=(), keyline="esc back", **_kw):
            frames.append(list(body))
            return {}

        def field(prompt, hint, around=None, **_kw):
            rows.append(around("typed here"))
            return None
        with patch.object(terminal, "width", return_value=40), \
                patch.object(terminal, "height", return_value=8), \
                patch.object(terminal, "frame", side_effect=frame), \
                patch.object(terminal, "field", side_effect=field), \
                patch.object(terminal, "read_key",
                             side_effect=[Key("down"), Key("enter"), Key("esc")]):
            menu.config_discord()
        keys = len(terminal.key_line(menu.ADD_KEYS["choose"][0] + "   esc back"))
        for body in frames:
            self.assertLessEqual(2 + len(body) + 1 + keys, 8, body)
        opened = next(body for body in frames if "typed here" in body)
        self.assertEqual(rows, [3 + opened.index("typed here")])   # the cursor on its line

    def test_no_webhook_is_not_connected_and_no_user_id_names_no_one(self):
        (config.SECRETS / "discord_user_id").unlink()
        self.assertEqual(self.row(), "webhook …a1B2c3")
        (config.SECRETS / "discord_webhook").unlink()
        self.assertEqual(self.row(), "not connected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
