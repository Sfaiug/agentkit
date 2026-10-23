"""A test's sink outranks the owner's webhook, and `ak notify --check` asks the webhook itself.

`AK_NOTIFY_SINK` is what keeps a suite from paging the owner: while it is set, a page goes to
the sink or nowhere, never to the webhook a host names, and ak says on stderr and in
`AK_NOTIFY_SINK_LOG` that it turned one away, so a suite whose run aimed at the owner fails on
that line.  `--check` proves the configured webhook is live with a GET, which posts no page, so
it asks the webhook as configured whatever the sink is, and its exit code tells a person "none
configured" (2) from "configured but not answering 200" (1).  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, before a seat of
tests/fixtures/akseat.py, with loopback servers of tests/fixtures/sink.py as webhook and sink.
"""

import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

DIVERTED = ("AK_NOTIFY_SINK is set; this notification went to the test sink and not to the "
            "configured webhook")


def servers(case):
    """A webhook server and, opened after it so that `AK_NOTIFY_SINK` names it, a sink."""
    webhook = Sink(case.home, "/api/webhooks/7/token?thread_id=9")
    case.addClassCleanup(webhook.close)
    sink = Sink(case.home)
    case.addClassCleanup(sink.close)     # first, so the Home gets its own sink back
    return webhook, sink


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheSinkShadowsTheWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.webhook, cls.sink = servers(cls)

    def ask(self, seat, env):
        Seat(self.home, seat)
        notes = self.home.path / f"sink-notes-{seat}.log"
        done = self.home.ak("notify", "needs", "Which branch?", "--session", seat,
                            env={"AK_NOTIFY_SINK_LOG": str(notes), **env})
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(f"notify: {DIVERTED}", done.err.splitlines())
        self.assertEqual(notes.read_text().splitlines(), [DIVERTED])
        return done

    def test_a_page_goes_to_the_sink_and_never_to_a_webhook_however_it_is_configured(self):
        for seat, where in (("fix-api", "environment"), ("fix-web", "secrets file")):
            with self.subTest(where):
                if where == "secrets file":
                    self.home.write(".agentkit/secrets/discord_webhook", self.webhook.url + "\n")
                    env = {}
                else:
                    env = {"AGENTKIT_DISCORD_WEBHOOK": self.webhook.url}
                self.ask(seat, env)
                self.assertEqual(self.sink.pages().count(f"🙋 Needs you · {seat}"), 1)
                self.assertEqual(self.webhook.requests, [])

    def test_a_sink_that_is_not_a_url_posts_the_page_nowhere(self):
        before = len(self.sink.requests)
        self.ask("fix-cli", {"AK_NOTIFY_SINK": "dry-run",
                             "AGENTKIT_DISCORD_WEBHOOK": self.webhook.url})
        self.assertEqual(len(self.sink.requests), before)
        self.assertEqual(self.webhook.requests, [])


class CheckTheWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.webhook, cls.sink = servers(cls)

    def check(self, webhook=None, code=1):
        done = self.home.ak("notify", "--check", env={"AGENTKIT_DISCORD_WEBHOOK": webhook})
        self.assertEqual(done.code, code, done)
        return done

    def test_with_no_webhook_configured_it_exits_2_and_says_where_one_goes(self):
        secret = self.home.path / ".agentkit" / "secrets" / "discord_webhook"
        for webhook in (None, "  "):
            with self.subTest(webhook=webhook):
                done = self.check(webhook, code=2)
                self.assertEqual(done.err.splitlines(), [
                    f"ak notify: --check: no webhook configured; put one in {secret} or "
                    "$AGENTKIT_DISCORD_WEBHOOK"])

    def test_a_webhook_that_is_not_http_fails_without_asking_anything(self):
        before = len(self.webhook.requests)
        done = self.check("ftp://x")
        self.assertEqual(done.err.splitlines(),
                         ["notify: fail (the configured webhook is not an http(s) URL)"])
        self.assertEqual(len(self.webhook.requests), before)

    def test_it_gets_the_webhook_as_configured_and_reports_its_status(self):
        self.webhook.script(200, 404)
        before = len(self.webhook.requests)
        for code, said in ((0, "notify: ok (200)"), (1, "notify: fail (404)")):
            with self.subTest(said):
                self.assertEqual(self.check(self.webhook.url, code).out.splitlines(), [said])
        asked = self.webhook.requests[before:]
        self.assertEqual([(r.method, r.path, r.query, r.body) for r in asked],
                         [("GET", "/api/webhooks/7/token", {"thread_id": "9"}, b"")] * 2)
        self.assertEqual(self.sink.requests, [])

    def test_the_environment_outranks_the_secrets_file(self):
        self.home.write(".agentkit/secrets/discord_webhook", self.webhook.url + "\n")
        self.addCleanup((self.home.path / ".agentkit/secrets/discord_webhook").unlink)
        self.assertEqual(self.check(code=0).out.splitlines(), ["notify: ok (200)"])
        done = self.check("ftp://x")
        self.assertEqual(done.err.splitlines(),
                         ["notify: fail (the configured webhook is not an http(s) URL)"])

    def test_a_webhook_nobody_answers_fails_and_keeps_its_url_out_of_what_it_says(self):
        with socket.socket() as probe:      # a loopback port nothing listens on once closed
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        url = f"http://127.0.0.1:{port}/api/webhooks/7/secret-token"
        done = self.check(url)
        self.assertTrue(done.err.startswith("notify: fail (no response"), done.err)
        self.assertNotIn("secret-token", done.out + done.err)


if __name__ == "__main__":
    unittest.main()
