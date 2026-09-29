"""`+ add a model` lists what each provider offers today, not a table updated by hand.

`adapters/claude.sh models` asks Anthropic's models API a page at a time and answers each model
with its label and the efforts its `capabilities.effort` supports, weakest first, `none` where
it takes none; `adapters/muse.sh models` asks `muse serve`'s `model/list`.  A listing that
fails, is slow or names nothing leaves the `[catalog]` table, as before.

Offline: every HOME is a temporary directory holding a dummy token, $ANTHROPIC_BASE_URL names a
fake models API on the loopback, and `muse` is a stub first on PATH that answers MSP from the
test's own listing.  No provider is asked anything.
"""

import http.server
import json
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config  # noqa: E402

TOKEN = "sk-ant-oat01-acme-worker"
LEVELS = ("low", "medium", "high", "xhigh", "max")


def claude_model(model, name, efforts=LEVELS):
    """One row of the models API: every level named, supported or not, as the API does; None
    for a model whose capabilities name no effort at all."""
    capabilities = {"batch": {"supported": True}}
    if efforts is not None:
        capabilities["effort"] = {"supported": bool(efforts),
                                  **{level: {"supported": level in efforts} for level in LEVELS}}
    return {"type": "model", "id": model, "display_name": name, "capabilities": capabilities}


# Three pages, keyed by the `after_id` that asks for each: a dated id the table knows undated,
# and one model with no effort capability.
PAGES = {
    None: [claude_model("claude-sonnet-5-5", "Claude Sonnet 5.5"),
           claude_model("claude-sonnet-4-6", "Claude Sonnet 4.6", ("low", "medium", "high", "max"))],
    "claude-sonnet-4-6": [claude_model("claude-haiku-4-5-20251001", "Claude Haiku 4.5", ())],
    "claude-haiku-4-5-20251001": [claude_model("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5",
                                               None)],
}

# `model/list` as muse 1.4.1 answers it, trimmed, plus a row whose efforts it calls unknown.
MUSE_LIST = {"models": [
    {"modelId": "muse-spark-1.4", "displayLabel": "muse-spark-1.4", "isDefault": False,
     "variants": ["minimal", "low", "medium", "high", "xhigh", "max"]},
    {"modelId": "muse-spark-1.3-contributor", "displayLabel": "muse-spark-1.3-contributor",
     "isDefault": True, "variants": ["minimal", "low", "medium", "high", "xhigh", "max"]},
    {"modelId": "muse-spark-lab", "displayLabel": "Muse Spark Lab", "isDefault": False,
     "variants": "unknown"},
], "profileId": "tbh", "providerId": "meta", "source": "providerCatalog"}

# A stub `muse`: logs its arguments and what it was sent, sleeps its seconds, then answers.
MUSE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$STUB_LOG"
cat >>"$STUB_LOG.stdin"
[ {sleep} = 0 ] || sleep {sleep}
cat -- {listing}
exit {rc}
"""


class FakeAPI(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        server = self.server
        server.asked.append((self.path, dict(self.headers)))
        after = parse_qs(urlsplit(self.path).query).get("after_id", [None])[0]
        if server.slow:
            server.release.wait(30)
            return
        if after in server.fail or urlsplit(self.path).path != "/v1/models":
            self.send_error(500)
            return
        data = PAGES[after]
        more = data[-1]["id"] in PAGES
        body = json.dumps({"data": data, "has_more": more, "first_id": data[0]["id"],
                           "last_id": data[-1]["id"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def lines(text):
    return [line.split("\t") for line in text.splitlines()]


class LiveCatalog(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".live-catalog-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        (self.home / ".agentkit/secrets").mkdir(parents=True)
        (self.home / ".agentkit/secrets/claude_oauth_token").write_text(TOKEN + "\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # macOS's Keychain would answer for the seat login; nothing here may
        (self.bin / "security").write_text("#!/bin/sh\nexit 1\n")
        (self.bin / "security").chmod(0o755)
        self.log = self.root / "calls.log"
        self.stub_muse(rc=1)
        self.api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        self.api.daemon_threads = True
        self.api.asked, self.api.fail, self.api.slow = [], set(), False
        self.api.release = threading.Event()
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)
        self.addCleanup(self.api.release.set)
        # a clean environment: no login, account or config home of the caller's reaches it
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/local/bin:/usr/bin:/bin",
                    "LANG": "C.UTF-8", "STUB_LOG": str(self.log),
                    "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.api.server_address[1]}"}

    def stub_muse(self, listing="/dev/null", rc=0, sleep=0):
        path = self.bin / "muse"
        path.write_text(MUSE.format(listing=shlex.quote(str(listing)), rc=rc, sleep=sleep))
        path.chmod(0o755)

    def models(self, harness, **env):
        proc = subprocess.run(["bash", str(REPO / f"adapters/{harness}.sh"), "models"],
                              capture_output=True, text=True, timeout=60,
                              env={**self.env, **env})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return lines(proc.stdout)

    def table(self, harness):
        return [[model["id"], model["label"], " ".join(model["efforts"])]
                for model in config.catalog_table(harness)]

    # -- Claude -------------------------------------------------------------------------------

    def test_claude_lists_every_page_with_labels_and_efforts(self):
        self.assertEqual(self.models("claude"), [
            ["claude-sonnet-5-5", "Sonnet 5.5", "low medium high xhigh max"],
            ["claude-sonnet-4-6", "Sonnet 4.6", "low medium high max"],
            # dated, and known undated to the table: the table's id, so an added Haiku
            # stays the model added
            ["claude-haiku-4-5", "Haiku 4.5", "none"],
            # no effort capability at all: it runs at none; unknown to the table: its own id
            ["claude-sonnet-4-5-20250929", "Sonnet 4.5", "none"],
        ])
        self.assertEqual([path for path, _ in self.api.asked], [
            "/v1/models?limit=1000",
            "/v1/models?limit=1000&after_id=claude-sonnet-4-6",
            "/v1/models?limit=1000&after_id=claude-haiku-4-5-20251001",
        ])
        headers = self.api.asked[0][1]
        self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(headers["anthropic-beta"], "oauth-2025-04-20")

    def test_claude_asks_with_the_accounts_own_login(self):
        # an account's worker token, then with none the seat login of its own config home
        secrets = self.home / ".agentkit/secrets"
        (secrets / "claude_oauth_token.acme").write_text("sk-ant-oat01-acme-second\n")
        self.models("claude", AGENTKIT_ACCOUNT="acme")
        (secrets / "claude_oauth_token.acme").unlink()
        seat = self.home / ".claude-acme"
        seat.mkdir()
        (seat / ".credentials.json").write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "sk-ant-oat01-acme-seat"}}))
        self.models("claude", AGENTKIT_ACCOUNT="acme")
        self.assertEqual([headers["Authorization"] for _, headers in self.api.asked[::3]],
                         ["Bearer sk-ant-oat01-acme-second", "Bearer sk-ant-oat01-acme-seat"])

    def test_claude_falls_back_to_the_table_when_the_api_fails_or_is_slow(self):
        table = self.table("claude")
        self.api.fail = {None}                                   # refused at once
        self.assertEqual(self.models("claude"), table)
        self.api.fail = {"claude-haiku-4-5-20251001"}            # the last page refused
        self.assertEqual(self.models("claude"), table, "never half a listing")
        self.api.fail, self.api.slow = set(), True
        started = time.monotonic()
        self.assertEqual(self.models("claude"), table)
        self.assertLess(time.monotonic() - started, 15, "the listing is given ten seconds")
        # and with no login at all nothing is asked
        (self.home / ".agentkit/secrets/claude_oauth_token").unlink()
        asked = len(self.api.asked)
        self.assertEqual(self.models("claude"), table)
        self.assertEqual(len(self.api.asked), asked)

    # -- Muse ---------------------------------------------------------------------------------

    def muse_answer(self, result):
        listing = self.root / "muse-serve.jsonl"
        listing.write_text(
            json.dumps({"id": 1, "jsonrpc": "2.0", "result": {"serverInfo": {"name": "muse"}}})
            + "\n" + json.dumps({"id": 2, "jsonrpc": "2.0", "result": result}) + "\n")
        return listing

    def test_muse_lists_its_model_list(self):
        self.stub_muse(self.muse_answer(MUSE_LIST))
        self.assertEqual(self.models("muse"), [
            ["muse-spark-1.4", "muse-spark-1.4", "minimal low medium high xhigh max"],
            ["muse-spark-1.3-contributor", "muse-spark-1.3-contributor",
             "minimal low medium high xhigh max"],
            ["muse-spark-lab", "Muse Spark Lab", ""],            # its efforts go unsaid
        ])
        self.assertEqual(self.log.read_text(), "serve --no-session-log\n")
        sent = [json.loads(line) for line in Path(f"{self.log}.stdin").read_text().splitlines()]
        self.assertEqual([message["method"] for message in sent],
                         ["initialize", "initialized", "model/list"])
        self.assertEqual(sent[2]["id"], 2)

    def test_muse_falls_back_to_the_table_when_its_list_fails_is_slow_or_empty(self):
        table = self.table("muse")
        self.stub_muse(self.muse_answer(MUSE_LIST), rc=1)
        self.assertEqual(self.models("muse"), table)
        # a login-less host answers from a bundled catalog with nothing in it
        self.stub_muse(self.muse_answer({"models": [], "profileId": None, "providerId": "meta",
                                         "source": "bundledCatalog"}))
        self.assertEqual(self.models("muse"), table)
        self.stub_muse(self.muse_answer(MUSE_LIST), sleep=30)
        started = time.monotonic()
        self.assertEqual(self.models("muse"), table)
        self.assertLess(time.monotonic() - started, 20, "the listing is given ten seconds")


if __name__ == "__main__":
    unittest.main()
