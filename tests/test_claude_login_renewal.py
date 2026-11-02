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
import signal
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]

# A fake claude: one line per turn -- the login's directory, the token beside it, the prompt,
# and its arguments -- then, unless told to fail, a renewed pair written where Claude Code
# writes it. `FAKE_SLEEP` holds the turn open, the way a real one takes seconds, and the files
# `hold` and `hold-renewed` hold it before and after renewing.  `auth logout` removes the login
# of the directory it runs in.
FAKE_CLAUDE = r"""#!/usr/bin/env bash
dir=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
[ "$*" != "auth logout" ] || exec rm "$dir/.credentials.json"
printf '%s|%s|%s|%s\n' "$dir" "${CLAUDE_CODE_OAUTH_TOKEN-unset}" "$(cat)" "$(printf '[%s]' "$@")" \
  >>"$FAKE/turns"
jq -r .claudeAiOauth.expiresAt "$dir/.credentials.json" >>"$FAKE/told"
sleep "${FAKE_SLEEP:-0}"
while [ -e "$FAKE/hold" ]; do sleep 0.02; done
[ ! -e "$FAKE/fail" ] || { echo "OAuth token refresh failed" >&2; exit 1; }
printf '{"claudeAiOauth":{"accessToken":"renewed","refreshToken":"refresh-2","expiresAt":%s}}' \
  "$(( ($(date +%s) + 28800) * 1000 ))" >"$dir/.credentials.json"
touch "$FAKE/renewed"
while [ -e "$FAKE/hold-renewed" ]; do sleep 0.02; done
echo Hello
"""

# A fake curl: the bearer token out of the `-H @file` header, one line per ask, and a 200.
FAKE_CURL = r"""#!/usr/bin/env bash
hf=""; prev=""
for a in "$@"; do [ "$prev" != -H ] || case "$a" in @*) hf=${a#@} ;; esac; prev=$a; done
grep '^Authorization:' "$hf" | cut -d' ' -f3 >>"$FAKE/asked"
printf '{"limits":[]}\n200\n'
"""

# with what every session ak starts runs with (adapters/claude.sh's PINS)
TURN = ("[-p][--model][haiku][--tools][][--no-session-persistence][--settings]"
        '[{"permissions":{"defaultMode":"bypassPermissions"},"crossSessionInbound":"refuse",'
        '"switchModelsOnFlag":true}]')
LAPSED = 1_000_000_000_000        # 2001, in milliseconds
FRESH = 4_102_444_800_000         # 2100


class LoginRenewal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-claude-renewal-", dir=REPO)
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
        # in a group of its own, as `config.run_adapter` runs it
        return subprocess.Popen(["bash", str(REPO / "adapters" / "claude.sh"), *argv],
                                process_group=0, env={**self.env, "AGENTKIT_ACCOUNT": account, **env},
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

    def in_(self, minutes):
        return int((time.time() + minutes * 60) * 1000)

    def test_a_login_with_ninety_minutes_left_is_renewed(self):
        self.login("second", self.in_(80))
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        self.assertEqual(len(self.turns()), 1)
        self.assertLess(int(self.lines("told")[-1]), self.in_(5))    # where Claude Code renews
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        self.assertEqual(len(self.turns()), 1)      # renewed, it has eight hours

    def test_a_login_past_ninety_minutes_is_left_and_one_that_did_not_renew_reads_as_it_did(self):
        self.login("second", self.in_(100))
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        self.assertEqual(self.turns(), [])
        (self.fake / "fail").touch()
        creds = self.login("second", self.in_(80))
        before = creds.read_text()
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        self.assertEqual(len(self.turns()), 1)
        self.assertEqual(creds.read_text(), before)

    def held_turn(self, hold, until):
        """An ask whose turn is held by the file `hold`, once the file `until` is there."""
        (self.fake / hold).touch()
        self.addCleanup((self.fake / hold).unlink, missing_ok=True)
        proc = self.start("second", "auth", "seat")
        self.addCleanup(proc.communicate)
        deadline = time.monotonic() + 30
        while not (self.fake / until).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue((self.fake / until).exists())
        return proc

    def killed(self, proc):
        """What `config.run_adapter`'s timeout does to a call."""
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()

    def mcp_saved(self, creds, token):
        """A native session's save of an MCP server's login, the way it replaces the file."""
        saved = json.loads(creds.read_text())
        saved["mcpOAuth"] = {"acme": {"accessToken": token}}
        creds.write_text(json.dumps(saved))
        return saved

    def test_a_turn_killed_before_renewing_leaves_the_login_true(self):
        creds = self.login("second", self.in_(80))
        before = creds.read_text()
        self.killed(self.held_turn("hold", "turns"))
        self.assertEqual(creds.read_text(), before)
        (self.fake / "hold").unlink()
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)    # the next ask renews it
        self.assertEqual(json.loads(creds.read_text())["claudeAiOauth"]["accessToken"], "renewed")

    def test_a_turn_killed_after_renewing_loses_no_renewal(self):
        creds = self.login("second", self.in_(80))
        self.killed(self.held_turn("hold-renewed", "renewed"))
        (self.fake / "hold-renewed").unlink()
        self.mcp_saved(creds, "new-mcp")
        (self.fake / "fail").touch()        # the login renewed is retired: only the kept one serves
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        kept = json.loads(creds.read_text())
        self.assertEqual(kept["claudeAiOauth"]["refreshToken"], "refresh-2")
        self.assertEqual(kept["mcpOAuth"]["acme"]["accessToken"], "new-mcp")
        self.assertEqual(len(self.turns()), 1)

    def test_a_kept_renewal_never_replaces_a_later_login(self):
        creds = self.login("second", self.in_(80))
        self.killed(self.held_turn("hold-renewed", "renewed"))
        (self.fake / "hold-renewed").unlink()
        later = json.loads(creds.read_text())
        later["claudeAiOauth"].update(accessToken="relogged", expiresAt=FRESH)
        creds.write_text(json.dumps(later))
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        self.assertEqual(json.loads(creds.read_text()), later)

    def test_what_a_session_saves_during_the_turn_stays(self):
        for failing in (True, False):
            with self.subTest(failing=failing):
                creds = self.login("second", self.in_(80))
                (self.fake / "fail").unlink(missing_ok=True)
                if failing:
                    (self.fake / "fail").touch()
                proc = self.held_turn("hold", "turns")
                saved = self.mcp_saved(creds, "new-mcp")
                (self.fake / "hold").unlink()
                proc.communicate(timeout=60)
                after = json.loads(creds.read_text())
                self.assertEqual(after["mcpOAuth"], saved["mcpOAuth"])
                self.assertEqual(after["claudeAiOauth"]["accessToken"],
                                 "seat" if failing else "renewed")

    def test_a_login_on_a_mac_waits_until_it_lapses(self):
        self.login("second", self.in_(80))
        (self.root / "bin" / "uname").write_text("#!/usr/bin/env bash\necho Darwin\n")
        (self.root / "bin" / "uname").chmod(0o755)
        self.assertEqual(self.ask("second", "auth", "seat")[0], 0)
        self.assertEqual(self.turns(), [])

    def test_logout_signs_out_its_own_login_and_worker_token_alone(self):
        usual, second = self.login("", FRESH), self.login("second", FRESH)
        secrets = self.root / ".agentkit" / "secrets"
        for _ in range(2):            # the second finds nothing left to sign out
            self.assertEqual(self.ask("second", "logout"), (0, ""))
            self.assertEqual([path.exists() for path in (
                second, secrets / "claude_oauth_token.second", usual,
                secrets / "claude_oauth_token")], [False, False, True, True])

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
