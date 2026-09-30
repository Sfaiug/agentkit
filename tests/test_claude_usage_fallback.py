"""Claude's meter asks once, with the login that is live, and names a Retry-After.

`claude.sh usage` sends one request per ask: the seat login's token while its `expiresAt`
is still in the future, else the worker token -- never both, so a second request can no
longer keep both tokens inside a 429 penalty, and a fallback answer can no longer replace
a good reading with an empty one. A refused ask names the endpoint's `Retry-After`, when it
named one, so the next ask waits for it. A fake `curl` and a fake `security` on PATH, and
a temporary HOME, so nothing here reaches a real endpoint or a real credential.
"""

import calendar
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters" / "claude.sh"

WORKER = "worker-token"
LOGIN = "login-token"
LIVE_MS = 4102444800000      # January 2030, in milliseconds, as the file writes it
OLD_MS = 1000000000000       # September 2001: expired before any seat was opened

# What the real endpoint answers a good token: the jq filter in `usage` keeps the entries
# carrying a reset and a percentage, and names the window off the group.
LIMITS = {"limits": [
    {"kind": "session", "group": "session", "percent": 25,
     "resets_at": "2026-09-22T10:00:00Z"},
    {"kind": "weekly", "group": "weekly", "percent": 50,
     "resets_at": "2026-09-28T10:00:00Z"},
]}

# A fake curl: the token out of the `-H @file` header, one line per probe appended
# to `asked`, the answer read from `resp-<token>` -- the code on the first line, the body on
# the rest -- and the response headers written to the `-D` file, with whatever the test put
# in `hdr-<token>` beside the status line, so each token's refusal or reading is a file this
# test writes.
FAKE_CURL = """#!/usr/bin/env bash
hf=""; df=""; prev=""
for a in "$@"; do
  case "$prev" in
    -H) case "$a" in @*) hf=${a#@};; esac ;;
    -D) df=$a ;;
  esac
  prev=$a
done
tok=$(grep '^Authorization:' "$hf" 2>/dev/null | head -1 | cut -d' ' -f3)
printf '%s\\n' "$tok" >>"$FAKE/asked"
resp="$FAKE/resp-$tok"
[ -f "$resp" ] || { printf '\\n000\\n'; exit 0; }
code=$(sed -n '1p' "$resp"); body=$(sed -n '2,$p' "$resp")
if [ -n "$df" ]; then
  { printf 'HTTP/1.1 %s\\r\\n' "$code"; cat "$FAKE/hdr-$tok" 2>/dev/null; printf '\\r\\n'; } >"$df"
fi
printf '%s\\n%s\\n' "$body" "$code"
"""

# A fake macOS Keychain: every consultation is a line in `security-asked`, and where the
# test wrote `keychain.json` its contents are the credentials, else there are none.
FAKE_SECURITY = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE/security-asked"
[ -f "$FAKE/keychain.json" ] || exit 1
cat "$FAKE/keychain.json"
"""


class UsageOneRequest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-claude-usage-fallback-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = self.root / "fake"
        self.fake.mkdir()
        bin = self.root / "bin"
        bin.mkdir()
        (bin / "curl").write_text(FAKE_CURL)
        (bin / "curl").chmod(0o755)
        (bin / "security").write_text(FAKE_SECURITY)
        (bin / "security").chmod(0o755)
        self.env = dict(os.environ)
        self.env["HOME"] = str(self.root)
        self.env["PATH"] = str(bin) + os.pathsep + self.env.get("PATH", "")
        self.env["FAKE"] = str(self.fake)
        # English weekday and month names, on any host: the HTTP date is parsed in them.
        self.env["LC_ALL"] = "C"
        # A leaked export would outrank the worker token file and hide the choice.
        self.env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        self.env.pop("AGENTKIT_ACCOUNT", None)

    # --- the fixture ------------------------------------------------------

    def answer(self, token, code, body="", headers=""):
        """What the endpoint says the next time that token is probed."""
        (self.fake / f"resp-{token}").write_text(f"{code}\n{body}\n")
        if headers:
            (self.fake / f"hdr-{token}").write_text(headers)
        else:
            (self.fake / f"hdr-{token}").unlink(missing_ok=True)

    def logged_out(self, account=None):
        """No seat login anywhere the adapter reads: neither the Keychain nor the file."""
        (self.fake / "keychain.json").unlink(missing_ok=True)
        home = self.root / (".claude" if account is None else f".claude-{account}")
        (home / ".credentials.json").unlink(missing_ok=True)

    def worker(self, token=WORKER, account=None):
        """A seat whose workers authenticate with that long-lived token."""
        secrets = self.root / ".agentkit" / "secrets"
        secrets.mkdir(parents=True, exist_ok=True)
        name = "claude_oauth_token" if account is None else f"claude_oauth_token.{account}"
        (secrets / name).write_text(token)

    def logged_in(self, token=LOGIN, expires_at=LIVE_MS, account=None, keychain=False):
        """A seat whose owner logged in: that token, expiring when told, in the login's own
        credentials file -- or in the Keychain, which the usual login reads first."""
        pair = {"claudeAiOauth": {"accessToken": token}}
        if expires_at is not None:
            pair["claudeAiOauth"]["expiresAt"] = expires_at
        if keychain:
            (self.fake / "keychain.json").write_text(json.dumps(pair))
            return
        home = self.root / (".claude" if account is None else f".claude-{account}")
        home.mkdir(parents=True, exist_ok=True)
        (home / ".credentials.json").write_text(json.dumps(pair))

    def usage(self, extra=None):
        """The `usage` verb's answer, parsed: it always exits 0 with one JSON object."""
        env = dict(self.env, **(extra or {}))
        proc = subprocess.run(["bash", str(ADAPTER), "usage"], env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def asked(self):
        """Every token the endpoint was probed with, in order."""
        try:
            return (self.fake / "asked").read_text().split()
        except OSError:
            return []

    def meters(self):
        """The readings a 200 with LIMITS must come back as."""
        return [
            {"name": "session", "used": 25,
             "resets_at": calendar.timegm((2026, 9, 22, 10, 0, 0)),
             "window_secs": 18000},
            {"name": "weekly", "used": 50,
             "resets_at": calendar.timegm((2026, 9, 28, 10, 0, 0)),
             "window_secs": 604800},
        ]

    # --- one request, with the login that is live -------------------------

    def test_a_live_login_is_asked_and_the_worker_token_is_never_sent(self):
        for label, keychain in (("file", False), ("keychain", True)):
            with self.subTest(label=label):
                (self.fake / "asked").unlink(missing_ok=True)
                self.worker()
                self.logged_out()
                self.logged_in(keychain=keychain)
                self.answer(WORKER, 200, json.dumps(LIMITS))
                self.answer(LOGIN, 200, json.dumps(LIMITS))
                out = self.usage()
                self.assertIsNone(out["error"])
                self.assertEqual(out["meters"], self.meters())
                self.assertEqual(self.asked(), [LOGIN])
                self.assertNotIn("retry_after", out)

    def test_a_refused_login_is_never_followed_by_the_worker_token(self):
        self.worker()
        self.logged_in()
        self.answer(LOGIN, 429, '{"error":"rate limited"}', "Retry-After: 953\r\n")
        self.answer(WORKER, 200, json.dumps(LIMITS))
        out = self.usage()
        self.assertEqual(out["meters"], [])
        self.assertIn("429", out["error"])
        self.assertEqual(out["retry_after"], 953)
        # The worker's 200 is never fetched: one ask is one request, whatever it says.
        self.assertEqual(self.asked(), [LOGIN])

    def test_a_login_past_its_expiry_sends_the_worker_token(self):
        for label, expires_at in (("expired milliseconds", OLD_MS),
                                  ("expired seconds", OLD_MS // 1000),
                                  ("no expiry recorded", None)):
            with self.subTest(label=label):
                (self.fake / "asked").unlink(missing_ok=True)
                self.worker()
                self.logged_in(expires_at=expires_at)
                self.answer(WORKER, 200, json.dumps(LIMITS))
                self.answer(LOGIN, 200, json.dumps(LIMITS))
                out = self.usage()
                self.assertIsNone(out["error"])
                self.assertEqual(out["meters"], self.meters())
                self.assertEqual(self.asked(), [WORKER])

    def test_a_seconds_expiry_in_the_future_is_live(self):
        self.worker()
        self.logged_in(expires_at=LIVE_MS // 1000)
        self.answer(WORKER, 200, json.dumps(LIMITS))
        self.answer(LOGIN, 200, json.dumps(LIMITS))
        out = self.usage()
        self.assertIsNone(out["error"])
        self.assertEqual(self.asked(), [LOGIN])

    def test_no_worker_token_probes_the_live_login_once(self):
        self.logged_in()
        self.answer(LOGIN, 200, json.dumps(LIMITS))
        out = self.usage()
        self.assertIsNone(out["error"])
        self.assertEqual(out["meters"], self.meters())
        self.assertEqual(self.asked(), [LOGIN])

    def test_without_a_live_login_or_a_worker_token_nothing_is_asked(self):
        for label, expires_at in (("expired login", OLD_MS), ("no login", "absent")):
            with self.subTest(label=label):
                (self.fake / "asked").unlink(missing_ok=True)
                self.logged_out()
                if expires_at != "absent":
                    self.logged_in(expires_at=expires_at)
                out = self.usage()
                self.assertEqual(out["meters"], [])
                self.assertIn("no Claude Code OAuth token", out["error"])
                self.assertEqual(self.asked(), [])

    # --- the endpoint's own not-before ------------------------------------

    def test_a_refusal_names_its_retry_after(self):
        cases = (("seconds", "Retry-After: 2072\r\n", 2072),
                 ("lowercase", "retry-after: 953\r\n", 953),
                 ("surrounding whitespace", "Retry-After: \t 2072 \t\r\n", 2072),
                 ("leading zeros are decimal", "Retry-After: 02072\r\n", 2072),
                 ("a past date is no wait",
                  "Retry-After: Wed, 21 Oct 2015 07:28:00 GMT\r\n", None),
                 ("not a date", "Retry-After: soon\r\n", None),
                 ("no header", "", None))
        for label, headers, waited in cases:
            with self.subTest(label=label):
                (self.fake / "asked").unlink(missing_ok=True)
                self.logged_in()
                self.answer(LOGIN, 429, '{"error":"rate limited"}', headers)
                out = self.usage()
                self.assertEqual(out["meters"], [])
                self.assertIn("429", out["error"])
                self.assertEqual(self.asked(), [LOGIN])
                if waited is None:
                    self.assertNotIn("retry_after", out)
                else:
                    self.assertEqual(out["retry_after"], waited)

    def test_a_refusal_names_a_future_http_date_in_seconds(self):
        self.logged_in()
        stamp = time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                              time.gmtime(time.time() + 3600))
        self.answer(LOGIN, 429, '{"error":"rate limited"}', f"Retry-After: {stamp}\r\n")
        out = self.usage()
        self.assertIn("429", out["error"])
        # The date, in seconds from when the adapter read it: about an hour, never exact.
        self.assertTrue(3590 <= out["retry_after"] <= 3600, out)

    # --- a named account --------------------------------------------------

    def test_a_named_account_reads_its_own_login_and_worker_token(self):
        self.worker("usual-worker")
        self.logged_in("usual-login")
        self.answer("usual-login", 200, json.dumps(LIMITS))
        self.answer("usual-worker", 200, json.dumps(LIMITS))
        self.worker("second-worker", account="second")
        self.logged_in("second-login", account="second")
        self.answer("second-login", 200, json.dumps(LIMITS))
        self.answer("second-worker", 200, json.dumps(LIMITS))
        out = self.usage({"AGENTKIT_ACCOUNT": "second"})
        self.assertIsNone(out["error"])
        self.assertEqual(self.asked(), ["second-login"])
        # ... and once its login lapses, its worker token, never the usual login's.
        self.logged_in("second-login", expires_at=OLD_MS, account="second")
        (self.fake / "asked").unlink()
        out = self.usage({"AGENTKIT_ACCOUNT": "second"})
        self.assertIsNone(out["error"])
        self.assertEqual(self.asked(), ["second-worker"])


if __name__ == "__main__":
    unittest.main()
