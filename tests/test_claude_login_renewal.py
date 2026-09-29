"""A Claude seat login that lapsed for lack of use is renewed by Claude Code before ak reads it.

Claude Code renews the seat login only when it runs on it, so a login no seat keeps open --
a second subscription's -- lapses after some eight hours and stays lapsed. `auth seat` and
`usage` give a lapsed login that still holds a refresh token the smallest Claude Code turn,
one per login at a time, and then answer as they would for a fresh one. The real
`adapters/claude.sh`, a fake `claude` that renews the login it runs on, a fake `curl`, and a
temporary HOME: no real login, and nothing that reaches a network.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]

# A fake claude: one line per turn -- the login's directory, the token beside it, the prompt,
# and its arguments -- then, unless told to fail, a renewed pair written where Claude Code
# writes it. `FAKE_SLEEP` holds the turn open, the way a real one takes seconds.
FAKE_CLAUDE = r"""#!/usr/bin/env bash
dir=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
printf '%s|%s|%s|%s\n' "$dir" "${CLAUDE_CODE_OAUTH_TOKEN-unset}" "$(cat)" "$(printf '[%s]' "$@")" \
  >>"$FAKE/turns"
sleep "${FAKE_SLEEP:-0}"
[ ! -e "$FAKE/fail" ] || { echo "OAuth token refresh failed" >&2; exit 1; }
printf '{"claudeAiOauth":{"accessToken":"renewed","refreshToken":"refresh-2","expiresAt":%s}}' \
  "$(( ($(date +%s) + 28800) * 1000 ))" >"$dir/.credentials.json"
echo Hello
"""

# A fake curl: the bearer token out of the `-H @file` header, one line per ask, and a 200.
FAKE_CURL = r"""#!/usr/bin/env bash
hf=""; prev=""
for a in "$@"; do [ "$prev" != -H ] || case "$a" in @*) hf=${a#@} ;; esac; prev=$a; done
grep '^Authorization:' "$hf" | cut -d' ' -f3 >>"$FAKE/asked"
printf '{"limits":[]}\n200\n'
"""

TURN = "[-p][--model][haiku][--tools][][--no-session-persistence]"
LAPSED = 1_000_000_000_000        # 2001, in milliseconds
FRESH = 4_102_444_800_000         # 2100


class LoginRenewal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".claude-renewal-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = self.root / "fake"
        bin = self.root / "bin"
        for d in (self.fake, bin, self.root / ".agentkit" / "secrets"):
            d.mkdir(parents=True)
        for name, text in (("claude", FAKE_CLAUDE), ("curl", FAKE_CURL),
                           # no Keychain on any host this runs on: the login is the file
                           ("security", "#!/usr/bin/env bash\nexit 1\n")):
            (bin / name).write_text(text)
            (bin / name).chmod(0o755)
        for account in ("", "second"):
            (self.root / ".agentkit" / "secrets" /
             f"claude_oauth_token{'.' + account if account else ''}").write_text("worker\n")
        # What a worker on another subscription hands down: its account's directory and
        # token, which a renewal of the usual login must not take for that login's own.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("AK_", "AGENTKIT_"))}
        self.env.update(HOME=str(self.root), PATH=f"{bin}{os.pathsep}{self.env.get('PATH', '')}",
                        FAKE=str(self.fake), CLAUDE_CODE_OAUTH_TOKEN="worker-env",
                        CLAUDE_CONFIG_DIR=str(self.root / ".claude-elsewhere"))

    # --- the fixture ------------------------------------------------------

    def directory(self, account):
        return self.root / (f".claude-{account}" if account else ".claude")

    def login(self, account, expires, refresh="refresh-1"):
        """The seat login of that account, as Claude Code last left it."""
        creds = self.directory(account) / ".credentials.json"
        creds.parent.mkdir(exist_ok=True)
        creds.write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "seat", "refreshToken": refresh, "expiresAt": expires}}))
        for name in ("turns", "asked"):
            (self.fake / name).unlink(missing_ok=True)
        return creds

    def start(self, account, *argv, **env):
        return subprocess.Popen(["bash", str(REPO / "adapters" / "claude.sh"), *argv],
                                env={**self.env, "AGENTKIT_ACCOUNT": account, **env},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8")

    def ask(self, account, *argv, **env):
        """The adapter's exit code and every line it said."""
        proc = self.start(account, *argv, **env)
        out, err = proc.communicate(timeout=60)
        return proc.returncode, (out + err).strip()

    def lines(self, name):
        try:
            return (self.fake / name).read_text().splitlines()
        except OSError:
            return []

    def turns(self):
        return [line.split("|") for line in self.lines("turns")]

    # --- the four cases ---------------------------------------------------

    def test_a_lapsed_login_is_renewed_once_and_then_passes(self):
        for account in ("second", ""):
            for verb in ("auth", "usage"):
                with self.subTest(account=account or "default", verb=verb):
                    self.login(account, LAPSED)
                    if verb == "auth":
                        code, said = self.ask(account, "auth", "seat")
                        self.assertEqual(code, 0, said)
                        self.assertEqual(said, "claude: the OAuth token in "
                                         f"{self.directory(account)}/.credentials.json "
                                         "is still valid")
                    else:
                        code, said = self.ask(account, "usage")
                        self.assertIsNone(json.loads(said)["error"], said)
                        # asked with the renewed seat login, never the worker token
                        self.assertEqual(self.lines("asked"), ["renewed"])
                    # One turn, the cheapest, on that login's own directory with no token
                    # standing in for it.
                    self.assertEqual(self.turns(),
                                     [[str(self.directory(account)), "unset", "hi", TURN]])
                    # Renewed, the login is fresh: the next ask renews nothing.
                    self.assertEqual(self.ask(account, "auth", "seat")[0], 0)
                    self.assertEqual(len(self.turns()), 1)

    def test_a_fresh_login_is_never_touched(self):
        creds = self.login("second", FRESH)
        before = (creds.read_bytes(), creds.stat().st_mtime_ns)
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        code, said = self.ask("second", "usage")
        self.assertIsNone(json.loads(said)["error"], said)
        self.assertEqual(self.lines("asked"), ["seat"])
        self.assertEqual(self.turns(), [])
        self.assertEqual((creds.read_bytes(), creds.stat().st_mtime_ns), before)
        # Nor is a lapsed one with nothing to renew it from: only /login brings that back.
        self.login("second", LAPSED, refresh="")
        self.assertEqual(self.ask("second", "auth", "seat")[0], 1)
        self.assertEqual(self.turns(), [])

    def test_a_failed_renewal_still_says_run_login(self):
        (self.fake / "fail").touch()
        creds = self.login("second", LAPSED)
        code, said = self.ask("second", "auth", "seat")
        self.assertEqual((code, said),
                         (1, f"claude: the OAuth token in {creds} expired; run /login"))
        self.assertEqual(len(self.turns()), 1)
        # ... and `usage` falls back to the worker token, as it always did.
        code, said = self.ask("second", "usage")
        self.assertIsNone(json.loads(said)["error"], said)
        self.assertEqual(self.lines("asked"), ["worker"])

    def test_two_asks_at_once_renew_only_once(self):
        self.login("second", LAPSED)
        first = self.start("second", "usage", FAKE_SLEEP="2")
        # The second ask comes while the first one's turn is still renewing the login.
        deadline = time.monotonic() + 30
        while not self.turns() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(self.turns()), 1)
        second = self.start("second", "auth", "seat", FAKE_SLEEP="2")
        out, err = second.communicate(timeout=60)
        self.assertEqual(second.returncode, 0, out + err)
        out, err = first.communicate(timeout=60)
        self.assertIsNone(json.loads(out)["error"], out + err)
        self.assertEqual(self.lines("asked"), ["renewed"])
        self.assertEqual(len(self.turns()), 1)


if __name__ == "__main__":
    unittest.main()
