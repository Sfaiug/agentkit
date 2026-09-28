"""Claude's usage endpoint is asked only as often as it allows.

A Claude account's endpoint is asked at most once every fifteen minutes -- its harness's
own fact -- and never before the `Retry-After` of its last 429, whoever asks and in
whatever process. An ask that brings back no meters keeps the last real reading. The real
`adapters/claude.sh` and the real `adapters/claude.toml`, a fake `curl` that counts
requests and returns a `Retry-After`, a temporary HOME, and invented tokens: nothing here
reaches the real endpoint.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, PropertyMock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, usage  # noqa: E402
from agentkit.harness import Harness, load as harness_plugin  # noqa: E402

NOW = 1800000000.0
WEEK = 604800
FIFTEEN = 900

WORKER_DEFAULT = "tok-default"
WORKER_SECOND = "tok-second"

CONFIG = """[defaults]
orchestrator = "opus"
workers = ["opus"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "high"
provider = "anthropic"

[providers.anthropic]
accounts = ["default", "second"]
"""

# A fake curl: the token out of the `-H @file` header, one line per probe appended to
# `asked`, the answer read from `resp-<token>` -- the code on the first line, the body on
# the rest -- and the response headers written to the `-D` file, with whatever the test
# put in `hdr-<token>` beside the status line.
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


class PoliteClaude(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".claude-polite-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = self.root / "fake"
        bin = self.root / "bin"
        adapters = self.root / "adapters"
        for d in (self.fake, bin, adapters):
            d.mkdir()
        (bin / "curl").write_text(FAKE_CURL)
        (bin / "curl").chmod(0o755)
        # No Keychain on any host this runs on: the seat login is the credentials file.
        (bin / "security").write_text("#!/usr/bin/env bash\nexit 1\n")
        (bin / "security").chmod(0o755)
        (adapters / "claude.sh").symlink_to(REPO / "adapters/claude.sh")
        home = self.root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, key, home / key.lower()))
        self.stack.enter_context(patch.object(config, "HOME", home))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("AK_", "AGENTKIT_"))
               and k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN")}
        env.update(HOME=str(self.root), PATH=f"{bin}{os.pathsep}{env.get('PATH', '')}",
                   FAKE=str(self.fake), AGENTKIT_ADAPTER_DIR=str(adapters),
                   AK_RUN_DEPTH="0", AK_MAX_RUNS="0", AGENTKIT_DISCORD_WEBHOOK="off")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text(CONFIG)
        (config.SECRETS / "claude_oauth_token").write_text(WORKER_DEFAULT)
        (config.SECRETS / "claude_oauth_token.second").write_text(WORKER_SECOND)
        self.real_now = time.time()
        self.now = [NOW]
        self.stack.enter_context(patch.object(usage.time, "time",
                                              side_effect=lambda: self.now[0]))
        self.cfg = config.load()
        self.good(WORKER_DEFAULT, 40)
        self.good(WORKER_SECOND, 20)

    # --- the fixture ------------------------------------------------------

    def good(self, token, weekly, session=0):
        """What the endpoint answers that token: a week and a session this far spent."""
        def at(offset):
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now[0] + offset))
        body = {"limits": [
            {"kind": "weekly_all", "group": "weekly", "percent": weekly,
             "resets_at": at(3 * 86400)},
            {"kind": "session", "group": "session", "percent": session,
             "resets_at": at(3600)}]}
        self.answer(token, 200, json.dumps(body))

    def answer(self, token, code, body="", headers=""):
        """What the endpoint says the next time that token is asked, headers beside it."""
        (self.fake / f"resp-{token}").write_text(f"{code}\n{body}\n")
        if headers:
            (self.fake / f"hdr-{token}").write_text(headers)
        else:
            (self.fake / f"hdr-{token}").unlink(missing_ok=True)

    def asked(self):
        """Every token the endpoint was asked with, in order."""
        try:
            return (self.fake / "asked").read_text().split()
        except OSError:
            return []

    def used(self, account):
        """That account's weekly used%, as the last collect read it."""
        prov = usage.collect(self.cfg)["anthropic"]["accounts"][account]
        return [m["used"] for m in prov["meters"] if m["name"] == "weekly_all"]

    # --- the cadence ------------------------------------------------------

    def test_fifteen_minutes_is_the_harness_s_own_fact_and_the_minute_is_the_default(self):
        self.assertEqual(harness_plugin("claude").usage["probe_every"], FIFTEEN)
        self.assertEqual(usage._probe_every(self.cfg, "anthropic"), FIFTEEN)
        # A harness that names nothing, or names nothing usable, keeps today's minute.
        bare = {"models": {"m": {"provider": "p", "harness": "no-such-harness"}}}
        self.assertEqual(usage._probe_every(bare, "p"), usage.PROBE_EVERY)
        for said in ("soon", 0, -30, True, None):
            with self.subTest(said=said), \
                    patch.object(Harness, "usage", new_callable=PropertyMock) as facts:
                facts.return_value = {"probe_every": said}
                self.assertEqual(usage._probe_every(self.cfg, "anthropic"), usage.PROBE_EVERY)

    def test_each_account_is_asked_at_most_once_every_fifteen_minutes(self):
        usage.collect(self.cfg)
        self.assertEqual(self.asked(), [WORKER_DEFAULT, WORKER_SECOND])
        self.assertEqual(usage.PROBE_EVERY, 60)
        # Inside fifteen minutes no caller asks again: a refresh, `ak usage`, a pick.
        for step in (0, 1, FIFTEEN - 1):
            self.now[0] = NOW + step
            usage.collect(self.cfg)
            usage.collect(self.cfg, refresh=True)
            self.assertEqual(len(self.asked()), 2, step)
        self.now[0] = NOW + FIFTEEN
        usage.collect(self.cfg, refresh=True)
        self.assertEqual(len(self.asked()), 4)
        for _ in range(3):
            usage.collect(self.cfg, refresh=True)
        self.assertEqual(len(self.asked()), 4)

    def test_a_retry_after_outlives_the_cadence_on_its_own_account(self):
        usage.collect(self.cfg)
        self.now[0] += FIFTEEN
        self.answer(WORKER_DEFAULT, 429, '{"error":"slow down"}', "Retry-After: 2072\r\n")
        self.good(WORKER_SECOND, 25)
        providers = usage.collect(self.cfg, refresh=True)
        self.assertEqual(len(self.asked()), 4)
        default = providers["anthropic"]["accounts"]["default"]
        # The failed ask kept the last reading and named the wait beside it.
        self.assertEqual([m["used"] for m in default["meters"] if m["name"] == "weekly_all"],
                         [40])
        self.assertEqual(default["fetched_at"], NOW)
        self.assertIn("429", default["probe_error"])
        self.assertEqual(default["retry_after"], 2072)
        self.assertEqual(float((config.STATE / "anthropic.default-probe.retry").read_text()),
                         NOW + FIFTEEN + 2072)
        # ... while the other account read its fresh week.
        self.assertEqual([m["used"] for m in
                          providers["anthropic"]["accounts"]["second"]["meters"]
                          if m["name"] == "weekly_all"], [25])
        # Fifteen minutes on, past the cadence but inside the wait: the refused account is
        # not asked again -- not by a refresh, and not by a refused worker either -- and
        # its kept reading still stands.
        self.now[0] += FIFTEEN
        self.good(WORKER_SECOND, 30)
        providers = usage.collect(self.cfg, refresh=True)
        self.assertEqual(self.asked()[4:], [WORKER_SECOND])
        default = providers["anthropic"]["accounts"]["default"]
        self.assertEqual([m["used"] for m in default["meters"] if m["name"] == "weekly_all"],
                         [40])
        self.assertIn("429", default["probe_error"])
        usage.replenish(self.cfg, "anthropic")
        self.assertEqual(len(self.asked()), 5)
        # Deleting the snapshot buys no earlier ask: the wait is beside the lock, not in
        # it. Past the second account's own cadence, it is asked and the refused one is not.
        self.now[0] += FIFTEEN + 1
        (config.STATE / "usage.json").unlink()
        usage.collect(self.cfg, refresh=True)
        self.assertEqual(len(self.asked()), 6)
        self.assertEqual(self.asked()[5:], [WORKER_SECOND])
        # At the endpoint's own not-before the account is asked, and answers replace again.
        self.now[0] = NOW + FIFTEEN + 2072
        self.good(WORKER_DEFAULT, 45)
        providers = usage.collect(self.cfg, refresh=True)
        self.assertIn(WORKER_DEFAULT, self.asked()[6:])
        default = providers["anthropic"]["accounts"]["default"]
        self.assertEqual([m["used"] for m in default["meters"] if m["name"] == "weekly_all"],
                         [45])
        self.assertNotIn("probe_error", default)

    def test_a_retry_after_runs_from_when_the_answer_arrives(self):
        usage.collect(self.cfg)
        self.now[0] += FIFTEEN
        self.answer(WORKER_DEFAULT, 429, '{"error":"slow down"}', "Retry-After: 2072\r\n")
        real = usage._probe

        def slow(cfg, provider, now, account=None):
            out = real(cfg, provider, now, account)
            if account == "default":
                self.now[0] += 10   # the answer arrives ten seconds after the ask
            return out

        with patch.object(usage, "_probe", side_effect=slow):
            usage.collect(self.cfg, refresh=True)
        self.assertEqual(float((config.STATE / "anthropic.default-probe.retry").read_text()),
                         NOW + FIFTEEN + 10 + 2072)

    def test_another_process_inside_the_cadence_asks_nothing(self):
        # Real time, so the lock files this process writes are ones the next process reads.
        self.now[0] = self.real_now
        self.good(WORKER_DEFAULT, 40)
        self.good(WORKER_SECOND, 20)
        usage.collect(self.cfg)
        self.assertEqual(self.asked(), [WORKER_DEFAULT, WORKER_SECOND])
        script = ("import json, sys; sys.path.insert(0, %r); "
                  "from agentkit import config, usage; "
                  "prov = usage.collect(config.load(), refresh=True)['anthropic']; "
                  "print(json.dumps({'account': prov.get('account')}))" % str(REPO))
        proc = subprocess.run([sys.executable, "-c", script], cwd=self.root,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"account": "second"})
        self.assertEqual(self.asked(), [WORKER_DEFAULT, WORKER_SECOND])

    # --- a failed ask -----------------------------------------------------

    def test_an_ask_with_no_meters_keeps_the_last_reading(self):
        usage.collect(self.cfg)
        first = NOW + FIFTEEN
        cases = (("429", 429, '{"error":"slow down"}', "429"),
                 ("401", 401, '{"error":"expired"}', "401"),
                 ("5xx", 500, '{"error":"overloaded"}', "500"),
                 ("403", 403, '{"error":"forbidden"}', "403"))
        for index, (label, code, body, marker) in enumerate(cases):
            with self.subTest(label=label):
                self.now[0] = first + index * (FIFTEEN + 1)
                self.answer(WORKER_DEFAULT, code, body)
                default = usage.collect(self.cfg, refresh=True)["anthropic"]["accounts"]["default"]
                self.assertEqual([m["used"] for m in default["meters"]
                                  if m["name"] == "weekly_all"], [40])
                self.assertEqual(default["fetched_at"], NOW)
                self.assertIn(marker, default["probe_error"])
                self.assertEqual(default["stale_since"], first)   # since the first failure
        # A dropped answer is a failed ask too: no file for the token is no meters either.
        self.now[0] = first + len(cases) * (FIFTEEN + 1)
        (self.fake / f"resp-{WORKER_DEFAULT}").unlink()
        default = usage.collect(self.cfg, refresh=True)["anthropic"]["accounts"]["default"]
        self.assertEqual([m["used"] for m in default["meters"]
                          if m["name"] == "weekly_all"], [40])
        self.assertIn("000", default["probe_error"])
        # Only an answer with meters replaces them: a fresh week is the reading at once,
        # with nothing of the failures beside it.
        self.now[0] += FIFTEEN + 1
        self.good(WORKER_DEFAULT, 55)
        default = usage.collect(self.cfg, refresh=True)["anthropic"]["accounts"]["default"]
        self.assertEqual([m["used"] for m in default["meters"]
                          if m["name"] == "weekly_all"], [55])
        self.assertNotIn("probe_error", default)
        self.assertNotIn("stale_since", default)

    def test_kept_answers_keep_their_reading_whatever_failed(self):
        cached = {"meters": [{"name": "weekly", "used": 40}], "probed_at": NOW, "resets": 0.0}
        for label, error in (
                ("429", "unknown: HTTP 429 from api.anthropic.com/api/oauth/usage"),
                ("401", "unknown: HTTP 401 from api.anthropic.com/api/oauth/usage"),
                ("5xx", "unknown: HTTP 503 from api.anthropic.com/api/oauth/usage"),
                ("timeout", "unknown: claude.sh usage timed out after 30s"),
                ("anything else", "unknown: adapter returned no meters")):
            with self.subTest(label=label):
                kept = usage._kept(cached, {"meters": [], "error": error}, NOW + FIFTEEN)
                self.assertEqual(kept["meters"], cached["meters"])
                self.assertEqual(kept["fetched_at"], NOW)
                self.assertEqual(kept["probe_error"], error)
                self.assertEqual(kept["stale_since"], NOW + FIFTEEN)
        # A second failure keeps the first one's age, and a first failure with nothing kept
        # still says what happened.
        again = usage._kept(kept, {"meters": [], "error": "unknown: HTTP 500 x"}, NOW + 2 * FIFTEEN)
        self.assertEqual(again["stale_since"], NOW + FIFTEEN)
        first = usage._kept({}, {"meters": [], "error": "unknown: HTTP 401 x"}, NOW)
        self.assertEqual(first["meters"], [])
        self.assertIn("401", first["probe_error"])
        # An answer with meters, and a meterless harness's own answer, replace.
        fresh = {"meters": [{"name": "weekly", "used": 10}], "error": None}
        self.assertIs(usage._kept(cached, fresh, NOW), fresh)
        none = {"meters": [], "error": None, "none": True}
        self.assertIs(usage._kept(cached, none, NOW), none)

    def test_an_expired_seat_login_is_never_sent(self):
        (self.root / ".claude-second").mkdir()
        (self.root / ".claude-second" / ".credentials.json").write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "second-seat", "expiresAt": 1000000000000}}))
        self.answer("second-seat", 401, '{"error":"expired"}')
        usage.collect(self.cfg)
        # The expired login's 401 was never fetched, so there is nothing to replace the
        # reading the worker token's answer brings.
        self.assertEqual(self.asked(), [WORKER_DEFAULT, WORKER_SECOND])
        self.assertEqual(self.used("second"), [20])

    def test_a_first_ask_with_no_reading_reports_the_failure(self):
        self.answer(WORKER_DEFAULT, 401, '{"error":"expired"}')
        self.answer(WORKER_SECOND, 401, '{"error":"expired"}')
        providers = usage.collect(self.cfg)
        for account in ("default", "second"):
            prov = providers["anthropic"]["accounts"][account]
            self.assertEqual(prov["meters"], [])
            self.assertIn("401", prov["probe_error"])


if __name__ == "__main__":
    unittest.main()
