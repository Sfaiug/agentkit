"""The Claude meter falls back to the login token when the worker token is refused.

`claude.sh usage` probes the usage endpoint with the worker token first; the endpoint
answers some setup-minted tokens 429 while the seat's own login answers 200 at the same
second. A fake `curl` and a fake `security` on PATH, and a temporary HOME, so nothing
here reaches a real endpoint or a real credential.
"""

import calendar
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters" / "claude.sh"

WORKER = "worker-token"
LOGIN = "login-token"

# What the real endpoint answers a good token: the jq filter in `usage` keeps the entries
# carrying a reset and a percentage, and names the window off the group.
LIMITS = {"limits": [
    {"kind": "session", "group": "session", "percent": 25,
     "resets_at": "2026-09-22T10:00:00Z"},
    {"kind": "weekly", "group": "weekly", "percent": 50,
     "resets_at": "2026-09-28T10:00:00Z"},
]}

# A fake curl: the bearer token out of the `-H @file` header, one line per probe appended
# to `asked`, and the answer read from `resp-<token>` -- the code on the first line, the
# body on the rest -- so each token's refusal or reading is a file this test writes.
FAKE_CURL = """#!/usr/bin/env bash
hf=""; prev=""
for a in "$@"; do
  if [ "$prev" = "-H" ]; then case "$a" in @*) hf=${a#@};; esac; fi
  prev=$a
done
tok=$(sed -n 's/^Authorization: Bearer //p' "$hf" 2>/dev/null | head -1)
printf '%s\\n' "$tok" >>"$FAKE/asked"
resp="$FAKE/resp-$tok"
[ -f "$resp" ] || { printf '\\n000\\n'; exit 0; }
code=$(sed -n '1p' "$resp"); body=$(sed -n '2,$p' "$resp")
printf '%s\\n%s\\n' "$body" "$code"
"""

# A fake macOS Keychain: every consultation is a line in `security-asked`, and where the
# test wrote `keychain.json` its contents are the credentials, else there are none.
FAKE_SECURITY = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE/security-asked"
[ -f "$FAKE/keychain.json" ] || exit 1
cat "$FAKE/keychain.json"
"""


class UsageFallback(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".claude-usage-fallback-", dir=REPO)
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
        # A leaked export would outrank the worker token file and hide the fallback.
        self.env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    # --- the fixture ------------------------------------------------------

    def answer(self, token, code, body=""):
        """What the endpoint says the next time that bearer token is probed."""
        (self.fake / f"resp-{token}").write_text(f"{code}\n{body}\n")

    def worker(self, token=WORKER):
        """A seat whose workers authenticate with that long-lived token."""
        secrets = self.root / ".agentkit" / "secrets"
        secrets.mkdir(parents=True)
        (secrets / "claude_oauth_token").write_text(token)

    def logged_in(self, token=LOGIN):
        """A seat whose owner logged in: the credentials file carries that token."""
        claude = self.root / ".claude"
        claude.mkdir(parents=True)
        (claude / ".credentials.json").write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": token}}))

    def usage(self):
        """The `usage` verb's answer, parsed: it always exits 0 with one JSON object."""
        proc = subprocess.run(["bash", str(ADAPTER), "usage"], env=self.env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def asked(self):
        """Every bearer token the endpoint was probed with, in order."""
        try:
            return (self.fake / "asked").read_text().split()
        except OSError:
            return []

    def keychain_asked(self):
        try:
            return (self.fake / "security-asked").read_text().splitlines()
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

    # --- the fallback -----------------------------------------------------

    def test_a_worker_token_that_answers_means_the_login_is_never_read(self):
        self.worker()
        self.logged_in()
        self.answer(WORKER, 200, json.dumps(LIMITS))
        out = self.usage()
        self.assertIsNone(out["error"])
        self.assertEqual(out["meters"], self.meters())
        self.assertEqual(self.asked(), [WORKER])
        # The login is read through the Keychain first, so an unconsulted Keychain means
        # the credentials file was never read either.
        self.assertEqual(self.keychain_asked(), [])

    def test_a_refused_worker_falls_back_to_the_login_and_returns_its_meters(self):
        self.worker()
        self.logged_in()
        self.answer(WORKER, 429, '{"error":"rate limited"}')
        self.answer(LOGIN, 200, json.dumps(LIMITS))
        out = self.usage()
        self.assertIsNone(out["error"])
        self.assertEqual(out["meters"], self.meters())
        self.assertEqual(self.asked(), [WORKER, LOGIN])

    def test_two_refusals_report_the_login_tokens_answer(self):
        self.worker()
        self.logged_in()
        self.answer(WORKER, 429, '{"error":"rate limited"}')
        self.answer(LOGIN, 403, '{"error":"forbidden"}')
        out = self.usage()
        self.assertEqual(out["meters"], [])
        self.assertIn("403", out["error"])
        self.assertNotIn("429", out["error"])
        self.assertEqual(self.asked(), [WORKER, LOGIN])

    def test_no_worker_token_probes_the_login_once(self):
        self.logged_in()
        self.answer(LOGIN, 200, json.dumps(LIMITS))
        out = self.usage()
        self.assertIsNone(out["error"])
        self.assertEqual(out["meters"], self.meters())
        self.assertEqual(self.asked(), [LOGIN])


if __name__ == "__main__":
    unittest.main()
