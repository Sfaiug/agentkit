"""Grok Build plugs in as a fourth harness: adapter, manifest, config and picker.

Offline throughout: a fake `grok` on PATH (and a fake `curl` for the usage verb),
a temporary HOME, fixture captures, and no real token, no network, and nothing
written outside that HOME.
"""

import ast
import calendar
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, menu, run, terminal, usage, watch, worker  # noqa: E402

FIX = REPO / "tests/fixtures"
ADAPTER = REPO / "adapters/grokbuild.sh"
NOW = time.time()


class GrokSandbox(unittest.TestCase):
    """A temporary HOME with a fake `grok`, like the other adapter tests' hosts."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".grokbuild-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.state.mkdir(parents=True)
        (self.home / ".agentkit/config.toml").write_text(
            (REPO / "config.default.toml").read_text())
        self.grok_home = self.home / ".grok"
        self.grok_home.mkdir()
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.args_file = self.home / "grok-args.txt"
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        stack.enter_context(patch.object(config, "STATE", self.state))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.home), "GROK_HOME": str(self.grok_home),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "AGENTKIT_SESSION": "atoll",
            # OpenCode's config is this HOME's, which names no MiMo endpoint: mimo is payg,
            # never a plan the caller's own config would make it
            "OPENCODE_CONFIG_DIR": str(self.home / ".config/opencode")}))
        os.environ.pop(config.ADAPTER_DIR_ENV, None)   # the checkout's adapters, never a copy
        os.environ.pop("XAI_API_KEY", None)
        os.environ.pop("AK_RUN_ROLE", None)   # a seat's hooks run in a seat's env, not a worker's
        self.env = {**os.environ}

    def fake_grok(self, events=None, code=0):
        """A `grok` that records its argv and answers the fixture event stream."""
        stream = FIX / "grok-events.jsonl" if events is None else events
        (self.bin / "grok").write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" >{shlex.quote(str(self.args_file))}\n"
            f"cat {shlex.quote(str(stream))}\n"
            f"exit {code}\n")
        (self.bin / "grok").chmod(0o755)

    def grok_args(self):
        return self.args_file.read_text().splitlines()

    def adapter(self, *args, seat="atoll"):
        proc = subprocess.run([str(ADAPTER), *args], capture_output=True, text=True,
                              env={**self.env, "AGENTKIT_SESSION": seat})
        return proc


class RunCommand(GrokSandbox):
    def test_run_builds_the_headless_command_line(self):
        self.fake_grok()
        ws = self.home / "ws"
        ws.mkdir()
        prompt = self.home / "prompt.md"
        prompt.write_text("Reply with the single word ok.\n")
        out = self.home / "out"
        proc = self.adapter("run", "grok-4.7", "xhigh", str(ws), str(prompt), str(out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        args = self.grok_args()
        # -p carries the prompt text; the shell's $() eats its trailing newline, as usual
        self.assertEqual(args[0:2], ["-p", "Reply with the single word ok."])
        self.assertEqual(args[2:9], ["--model", "grok-4.7", "--reasoning-effort", "xhigh",
                                    "--always-approve", "--output-format",
                                    "streaming-messages-json"])
        # a turn without an id starts its own conversation under a fresh uuid
        self.assertEqual(args[9], "--session-id")
        uuid = args[10]
        self.assertRegex(uuid, r"^[0-9a-f-]{36}$", uuid)
        self.assertEqual(len(args), 11, args)
        self.assertEqual((out / "final.md").read_text(), "ok\n")
        self.assertEqual((out / "session_id").read_text(),
                         json.loads((FIX / "grok-events.jsonl").read_text().splitlines()[0])
                         ["session_id"])
        self.assertTrue((out / "stderr.log").is_file())
        self.assertEqual((out / "events.jsonl").read_bytes(),
                         (FIX / "grok-events.jsonl").read_bytes())

    def test_run_resume_continues_the_conversation(self):
        self.fake_grok()
        ws = self.home / "ws"
        ws.mkdir()
        prompt = self.home / "prompt.md"
        prompt.write_text("Again.\n")
        out = self.home / "out"
        proc = self.adapter("run", "grok-4.7", "xhigh", str(ws), str(prompt), str(out),
                            "2763f521-2dfd-427a-8ca6-7114f28d1ba7")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        args = self.grok_args()
        self.assertEqual(args[-2:], ["--resume", "2763f521-2dfd-427a-8ca6-7114f28d1ba7"])
        self.assertNotIn("--session-id", args)


class Auth(GrokSandbox):
    def test_auth_reads_the_fake_login_file(self):
        auth = self.grok_home / "auth.json"
        shutil.copy(FIX / "grok-auth-valid.json", auth)
        proc = self.adapter("auth")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("is saved", proc.stdout)
        seat = self.adapter("auth", "seat")
        self.assertEqual(seat.returncode, 0, seat.stderr)   # the same login, accepted
        shutil.copy(FIX / "grok-auth-expired.json", auth)
        proc = self.adapter("auth")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("expired", proc.stderr)
        auth.unlink()
        proc = self.adapter("auth")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("grok login", proc.stderr)

    def test_auth_passes_a_lapsed_key_with_a_refresh_token(self):
        # The key lives six hours and grok trades its refresh token for a fresh one whenever
        # it runs, so a key that lapsed while grok sat idle is still a login grok can use.
        # The verb reads the file and nothing else: no grok is run and the file is untouched.
        self.fake_grok()
        auth = self.grok_home / "auth.json"
        shutil.copy(FIX / "grok-auth-lapsed.json", auth)
        before = auth.read_bytes()
        for seat in ((), ("seat",)):
            with self.subTest(seat=seat):
                proc = self.adapter("auth", *seat)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("is saved", proc.stdout)
        self.assertFalse(self.args_file.exists())   # grok was never run
        self.assertEqual(auth.read_bytes(), before)
        # a refresh token whose key grok has yet to write is the same login
        auth.write_text(json.dumps({"https://auth.x.ai::fixture": {
            "auth_mode": "oidc", "refresh_token": "fixture.refresh.not.a.token"}}))
        proc = self.adapter("auth")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_auth_fails_a_lapsed_key_without_a_refresh_token(self):
        # Nothing to renew it with is expired, and a blank refresh token is none; an entry
        # with neither a key nor a refresh token carries no login at all.
        auth = self.grok_home / "auth.json"
        lapsed = json.loads((FIX / "grok-auth-lapsed.json").read_text())
        entry = lapsed["https://auth.x.ai::fixture"]
        for label, login, why in (
                ("no refresh token", (FIX / "grok-auth-expired.json").read_text(), "expired"),
                ("blank refresh token", json.dumps({"https://auth.x.ai::fixture": {
                    **entry, "refresh_token": " "}}), "expired"),
                ("neither", json.dumps({"https://auth.x.ai::fixture": {
                    "auth_mode": "oidc", "expires_at": entry["expires_at"]}}),
                 "no session token")):
            with self.subTest(label=label):
                auth.write_text(login)
                proc = self.adapter("auth")
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn(why, proc.stderr)
                self.assertIn("grok login", proc.stderr)


class UsageVerb(GrokSandbox):
    # A fake `curl` beside the fake `grok`: the billing probe is answered from the
    # `resp` file the test writes -- the code on the first line, the body on the
    # rest, 000 with no body where no file is -- so no usage test reaches a real
    # endpoint; a `resp.<key>` file answers that session key alone, and a `during.<key>`
    # file is a login saved over auth.json while that key's request was out.  The session
    # key the probe went out with and the URL it went to are appended to `asked` and
    # `asked-url`, under $HOME/fake beside the temp HOME.
    FAKE_CURL = """#!/bin/sh
dir="$HOME/fake"
hf=""; prev=""
for a in "$@"; do
  if [ "$prev" = "-H" ]; then case "$a" in @*) hf=${a#@};; esac; fi
  case "$a" in https://*) printf '%s\\n' "$a" >>"$dir/asked-url";; esac
  prev=$a
done
tok=$(cut -d' ' -f3 <"$hf" 2>/dev/null | head -1)
printf '%s\\n' "$tok" >>"$dir/asked"
[ ! -f "$dir/during.$tok" ] || cp "$dir/during.$tok" "$GROK_HOME/auth.json"
resp="$dir/resp"
[ ! -f "$resp.$tok" ] || resp="$resp.$tok"
[ -f "$resp" ] || { printf '\\n000\\n'; exit 0; }
code=$(sed -n '1p' "$resp"); body=$(sed -n '2,$p' "$resp")
printf '%s\\n%s\\n' "$body" "$code"
"""

    # The fake `grok` answers the one call the usage verb makes of it, `grok models`, the
    # way grok renews its own login: a `renewed` file under $HOME/fake is the fresh key it
    # traded the refresh token for, written over auth.json; a `refused` file is a refresh
    # token the IdP would not trade, so grok drops the login and says the session expired;
    # with neither it renews nothing -- no refresh token, or its IdP out of reach -- and
    # leaves the file be.  Each call's arguments
    # are appended to `grok-asked`.
    FAKE_GROK = """#!/bin/sh
dir="$HOME/fake"
printf '%s\\n' "$*" >>"$dir/grok-asked"
if [ -f "$dir/renewed" ]; then
  cp "$dir/renewed" "$GROK_HOME/auth.json"; echo 'You are logged in with grok.com.'
elif [ -f "$dir/refused" ]; then
  rm -f "$GROK_HOME/auth.json"
  echo 'Your session has expired. Run `grok login` to sign in again.' >&2
  echo 'You are not authenticated.'
else
  echo 'You are not authenticated.'
fi
"""

    def setUp(self):
        super().setUp()
        self.fake = self.home / "fake"
        self.fake.mkdir()
        for name, script in (("curl", self.FAKE_CURL), ("grok", self.FAKE_GROK)):
            (self.bin / name).write_text(script)
            (self.bin / name).chmod(0o755)

    def answer(self, code, body="", key=None):
        """What the billing endpoint says to the next probe, or to that key's: the code, then the body."""
        (self.fake / ("resp" if key is None else f"resp.{key}")).write_text(f"{code}\n{body}\n")

    def grok_asked(self):
        """The arguments of every grok call the usage verb made, in order."""
        try:
            return (self.fake / "grok-asked").read_text().splitlines()
        except OSError:
            return []

    def weekly(self):
        """The captured weekly credits body with its window around now, and that window's end."""
        body = json.loads((FIX / "grok-billing-weekly.json").read_text())
        end = int(time.time()) + 3 * 86400
        body["config"]["currentPeriod"].update(
            {edge: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(at))
             for edge, at in (("start", end - 604800), ("end", end))})
        return json.dumps(body), end

    def row(self, out):
        """The menu's Grok row, plain, drawn from that probe as the cached reading."""
        (self.state / "usage.json").write_text(json.dumps(
            {"fetched_at": out["probed_at"], "providers": {"xai": out}}))
        rows = [terminal.plain(line).strip() for line in menu.usage_lines(config.load(), 100)]
        return next(line for line in rows if line.startswith("Grok"))

    def asked_tokens(self):
        """Every session key the endpoint was probed with, in order."""
        try:
            return (self.fake / "asked").read_text().split()
        except OSError:
            return []

    def asked_urls(self):
        """Every URL the endpoint was probed at, in order."""
        try:
            return (self.fake / "asked-url").read_text().split()
        except OSError:
            return []

    def test_usage_answers_meter_entries_from_the_settings_cache(self):
        shutil.copy(FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
        shutil.copy(FIX / "grok-settings-meters.json",
                    self.grok_home / "settings_cache.json")
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["provider"], "xai")
        self.assertIsNone(data["error"])
        self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                          for m in data["meters"]],
                         [("weekly", 42, 1999999999, 604800),
                          ("session", 10, 1999999999, 18000)])
        self.assertNotIn("none", data)   # none only on the fallback path

    def test_usage_reports_none_only_on_the_fallback_path(self):
        shutil.copy(FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
        shutil.copy(FIX / "grok-settings-none.json",
                    self.grok_home / "settings_cache.json")
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual((data["provider"], data["meters"], data["error"]),
                         ("xai", [], None))
        self.assertIn("no meter", data["none"])
        (self.grok_home / "settings_cache.json").unlink()   # no cache at all: same answer
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual((data["meters"], data["error"]), ([], None))
        self.assertIn("no meter", data["none"])

    def test_usage_without_a_login_is_a_failed_probe(self):
        # no login is an error, never none: an unauthenticated xai must rank last like
        # claude and codex do, not neutrally, or the run parks waiting_login on it.  The
        # error rides JSON on exit 0, so usage.py asks the `auth` verb, whose no is what
        # puts `no login` on the menu row.
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["meters"], [])
        self.assertIn("grok login", data["error"])
        self.assertNotIn("none", data)
        out = usage._probe(config.load(), "xai", NOW)
        self.assertIsNotNone(out["error"])
        self.assertFalse(out["logged_in"])   # the auth verb was asked, and said no
        self.assertNotIn("none", out)
        self.assertEqual(menu.unread(out, [], [], NOW), "no login")
        path = os.pathsep.join(d for d in self.env["PATH"].split(os.pathsep)
                               if not (Path(d) / "grok").exists())
        proc = subprocess.run([str(ADAPTER), "usage"], capture_output=True, text=True,
                              env={**self.env, "PATH": path, "AGENTKIT_SESSION": "atoll"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not installed", json.loads(proc.stdout)["error"])
        shutil.copy(FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
        proc = self.adapter("usage")   # a login restores the neutral reading
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("no meter", json.loads(proc.stdout)["none"])

    def test_usage_answers_credit_meters_from_the_billing_endpoint(self):
        # Protobuf shape of the same credits fields: currentPeriod start/end as
        # seconds, type WEEKLY, so the headline meter is the weekly window and the
        # product usagePercent rides it.  used/monthlyLimit stay spend without an
        # allowance and must never be read as a percent.
        shutil.copy(FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
        self.answer(200, (FIX / "grok-billing-credits.json").read_text())
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["provider"], "xai")
        self.assertIsNone(data["error"])
        reset = calendar.timegm((2026, 9, 28, 0, 0, 0))
        self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                          for m in data["meters"]],
                         [("weekly", 37, reset, 604800),
                          ("build", 52, reset, 604800)])
        self.assertNotIn("none", data)
        # the probe went out once, with the session key, to the credits form
        self.assertEqual(self.asked_tokens(), ["fixture.not.a.token"])
        self.assertEqual(self.asked_urls(),
                         ["https://cli-chat-proxy.grok.com/v1/billing?format=credits"])

    def test_usage_answers_the_weekly_meter_from_the_credits_response(self):
        # The wire body of GET /v1/billing?format=credits, captured 2026-09-22: the
        # Usage limit tab's weekly window, currentPeriod as ISO instants, the percent
        # the panel prints, and the one product on that same window.
        shutil.copy(FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
        self.answer(200, (FIX / "grok-billing-weekly.json").read_text())
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["provider"], "xai")
        self.assertIsNone(data["error"])
        reset = calendar.timegm((2026, 9, 29, 0, 0, 0))
        self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                          for m in data["meters"]],
                         [("weekly", 50, reset, 604800),
                          ("GrokBuild", 50, reset, 604800)])
        self.assertNotIn("none", data)
        self.assertEqual(self.asked_urls(),
                         ["https://cli-chat-proxy.grok.com/v1/billing?format=credits"])

    def test_usage_names_every_failed_source_when_none_remains(self):
        # Every source tried and none a meter: the credits response is spend without a
        # percent, and the settings cache carries no subscription_usage entries.  The
        # same with the endpoint unreachable.  The reason names each source.
        shutil.copy(FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
        shutil.copy(FIX / "grok-settings-none.json",
                    self.grok_home / "settings_cache.json")
        self.answer(200, (FIX / "grok-billing-nometer.json").read_text())
        for label in ("meterless answer", "unreachable endpoint"):
            if label == "unreachable endpoint":
                (self.fake / "resp").unlink()
            with self.subTest(label=label):
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                data = json.loads(proc.stdout)
                self.assertEqual((data["provider"], data["meters"], data["error"]),
                                 ("xai", [], None))
                self.assertIn("no meter", data["none"])
                self.assertIn("format=credits", data["none"])
                self.assertIn("settings cache", data["none"])

    def test_usage_reports_none_when_every_source_is_meterless(self):
        # Every source tried and none a meter: the billing endpoint answers spend
        # without an allowance (captured verbatim 2026-09-22) and the settings cache
        # carries no subscription_usage entries -- then the same with the endpoint
        # unreachable.  Both keep the provider neutral, with the reason.
        shutil.copy(FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
        shutil.copy(FIX / "grok-settings-none.json",
                    self.grok_home / "settings_cache.json")
        self.answer(200, (FIX / "grok-billing-nometer.json").read_text())
        for label in ("meterless answer", "unreachable endpoint"):
            if label == "unreachable endpoint":
                (self.fake / "resp").unlink()   # no answer file: curl reports 000
            with self.subTest(label=label):
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                data = json.loads(proc.stdout)
                self.assertEqual((data["provider"], data["meters"], data["error"]),
                                 ("xai", [], None))
                self.assertIn("no meter", data["none"])
                self.assertIn("billing", data["none"])

    def test_usage_with_an_expired_login_is_a_failed_probe(self):
        # A refused billing probe is an expired login, not a missing meter: it fails
        # the probe like a missing login, so the provider ranks last instead of
        # reading neutral and parking the run waiting_login on it.
        shutil.copy(FIX / "grok-auth-expired.json", self.grok_home / "auth.json")
        self.answer(401, '{"error":"expired"}')
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["meters"], [])
        self.assertIn("grok login", data["error"])
        self.assertNotIn("none", data)
        out = usage._probe(config.load(), "xai", NOW)
        self.assertIsNotNone(out["error"])
        self.assertFalse(out["logged_in"])   # the auth verb was asked, and said expired
        self.assertNotIn("none", out)
        self.assertEqual(menu.unread(out, [], [], NOW), "no login")

    # The login grok writes when it renews: a fresh key beside the refresh token.  And a
    # refresh token grok has yet to write a key beside.
    RENEWED = {"https://auth.x.ai::fixture": {
        "key": "fixture.renewed.not.a.token", "auth_mode": "oidc",
        "refresh_token": "fixture.refresh.not.a.token", "expires_at": "2030-06-01T00:00:00Z"}}
    UNKEYED = {"https://auth.x.ai::fixture": {
        "auth_mode": "oidc", "refresh_token": "fixture.refresh.not.a.token"}}

    def test_usage_lets_grok_renew_a_lapsed_key_then_reads(self):
        # The key lapsed while grok sat idle: the endpoint refuses it, grok renews it the
        # way it does itself, and the renewed key reads the meter -- which is what the row
        # shows, never `no login`.  A refresh token with no key beside it is renewed before
        # anything is asked.
        (self.fake / "renewed").write_text(json.dumps(self.RENEWED))
        body, reset = self.weekly()
        self.answer(401, '{"error":"expired"}')
        self.answer(200, body, key="fixture.renewed.not.a.token")
        for label, login, asked in (
                ("lapsed key", (FIX / "grok-auth-lapsed.json").read_text(),
                 ["fixture.lapsed.not.a.token", "fixture.renewed.not.a.token"]),
                ("refresh token alone", json.dumps(self.UNKEYED),
                 ["fixture.renewed.not.a.token"])):
            with self.subTest(label=label):
                for name in ("asked", "grok-asked"):
                    (self.fake / name).unlink(missing_ok=True)
                (self.grok_home / "auth.json").write_text(login)
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                data = json.loads(proc.stdout)
                self.assertIsNone(data["error"])
                self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                                  for m in data["meters"]],
                                 [("weekly", 50, reset, 604800),
                                  ("GrokBuild", 50, reset, 604800)])
                # renewed by grok, then asked with the key grok wrote
                self.assertEqual(self.asked_tokens(), asked)
                self.assertEqual(self.grok_asked(), ["models"])
                self.assertEqual(json.loads((self.grok_home / "auth.json").read_text()),
                                 self.RENEWED)
                out = usage._probe(config.load(), "xai", time.time())
                self.assertIsNone(out["error"])
                self.assertNotIn("logged_in", out)   # nothing to ask the auth verb about
                self.assertRegex(self.row(out),
                                 r"^Grok\s+\S+\s+50% left · resets \w{3} \d\d:\d\d$")

    def test_usage_refused_after_renewal_is_no_login(self):
        # Grok had its chance and the endpoint still refuses: a real logout, in every shape
        # it takes -- a lapsed key with no refresh token, which grok leaves as it was; a
        # refresh token the IdP would not trade, which grok drops from auth.json as it says
        # the session expired, leaving no key to ask with; and a key grok did renew, from a
        # lapsed one or from a refresh token alone, that the endpoint refuses all the same.
        # Either way the `auth` verb says no, and the row says `no login`.
        lapsed = (FIX / "grok-auth-lapsed.json").read_text()
        for label, login, grok, asked in (
                ("no refresh token", (FIX / "grok-auth-expired.json").read_text(), None,
                 ["fixture.not.a.token", "fixture.not.a.token"]),
                ("refresh refused", lapsed, "refused", ["fixture.lapsed.not.a.token"]),
                ("renewed key refused", lapsed, "renewed",
                 ["fixture.lapsed.not.a.token", "fixture.renewed.not.a.token"]),
                ("key renewed from a refresh token refused", json.dumps(self.UNKEYED),
                 "renewed", ["fixture.renewed.not.a.token"])):
            with self.subTest(label=label):
                for name in ("asked", "grok-asked", "refused", "renewed"):
                    (self.fake / name).unlink(missing_ok=True)
                if grok:
                    (self.fake / grok).write_text(json.dumps(self.RENEWED))
                (self.grok_home / "auth.json").write_text(login)
                self.answer(401, '{"error":"expired"}')
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(self.grok_asked(), ["models"])
                self.assertEqual(self.asked_tokens(), asked)
                data = json.loads(proc.stdout)
                self.assertEqual(data["meters"], [])
                self.assertIn("grok login", data["error"])
                self.assertNotIn("none", data)
                auth = self.adapter("auth")
                self.assertEqual(auth.returncode, 1, auth.stdout)
                self.assertIn("grok login", auth.stderr)
                out = usage._probe(config.load(), "xai", time.time())
                self.assertFalse(out["logged_in"])   # the auth verb was asked, and said no
                self.assertEqual(menu.unread(out, [], [], time.time()), "no login")
                self.assertRegex(self.row(out), r"^Grok\s+—\s+no login$")

    def test_usage_keeps_the_login_when_grok_could_not_renew(self):
        # Grok could not reach its IdP just now: a refresh token with no key beside it stays
        # without one, and a lapsed key stays lapsed and is refused again.  Neither is the
        # endpoint refusing a key grok renewed, so nothing is written down: the `auth` verb
        # still says yes on the refresh token, and the row reads `not reached`, never
        # `no login`, until a later probe finds grok renewing.
        refused = self.state / "grok-refused"
        for label, login, asked in (
                ("refresh token alone", json.dumps(self.UNKEYED), []),
                ("lapsed key", (FIX / "grok-auth-lapsed.json").read_text(),
                 ["fixture.lapsed.not.a.token", "fixture.lapsed.not.a.token"])):
            with self.subTest(label=label):
                for name in ("asked", "grok-asked"):
                    (self.fake / name).unlink(missing_ok=True)
                (self.grok_home / "auth.json").write_text(login)
                self.answer(401, '{"error":"expired"}')
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(self.grok_asked(), ["models"])
                self.assertEqual(self.asked_tokens(), asked)
                self.assertIsNotNone(json.loads(proc.stdout)["error"])
                self.assertFalse(refused.exists())
                auth = self.adapter("auth")
                self.assertEqual(auth.returncode, 0, auth.stderr)
                out = usage._probe(config.load(), "xai", time.time())
                self.assertTrue(out["logged_in"])
                self.assertRegex(self.row(out), r"^Grok\s+—\s+not reached$")

    def test_a_refusal_names_the_key_that_was_sent(self):
        # The refusal is written down as the digest of the very key the endpoint refused,
        # never the key and never anything read after the answer: a login saved while that
        # request was out, and another login carrying the same expiry, are both logins
        # nobody refused.  The refused key itself stays a logout until the endpoint answers it.
        renewed = "fixture.renewed.not.a.token"
        another = {scope: {**entry, "key": "fixture.another.not.a.token"}
                   for scope, entry in self.RENEWED.items()}   # same expiry, another key
        refused = self.state / "grok-refused"
        (self.fake / "renewed").write_text(json.dumps(self.RENEWED))
        self.answer(401, '{"error":"expired"}')
        # a `grok login` lands while the renewed key's request is out
        (self.fake / f"during.{renewed}").write_text(json.dumps(another))
        shutil.copy(FIX / "grok-auth-lapsed.json", self.grok_home / "auth.json")
        self.adapter("usage")
        self.assertEqual(self.asked_tokens(), ["fixture.lapsed.not.a.token", renewed])
        self.assertEqual(refused.read_text().strip(), hashlib.sha256(renewed.encode()).hexdigest())
        self.assertNotIn("not.a.token", refused.read_text())
        auth = self.adapter("auth")
        self.assertEqual(auth.returncode, 0, auth.stderr)   # the login saved meanwhile stands
        # the refused key back in auth.json is refused; another with its expiry is not
        (self.fake / f"during.{renewed}").unlink()
        (self.grok_home / "auth.json").write_text(json.dumps(self.RENEWED))
        auth = self.adapter("auth")
        self.assertEqual(auth.returncode, 1, auth.stdout)
        self.assertIn("refused", auth.stderr)
        (self.grok_home / "auth.json").write_text(json.dumps(another))
        auth = self.adapter("auth")
        self.assertEqual(auth.returncode, 0, auth.stderr)
        # the endpoint answering the refused key after all lifts it
        (self.grok_home / "auth.json").write_text(json.dumps(self.RENEWED))
        body, _ = self.weekly()
        self.answer(200, body)
        self.assertIsNone(json.loads(self.adapter("usage").stdout)["error"])
        self.assertFalse(refused.exists())
        auth = self.adapter("auth")
        self.assertEqual(auth.returncode, 0, auth.stderr)


class NoMeterPicker(GrokSandbox):
    def providers(self):
        half_week = 302400
        return {
            "anthropic": {"provider": "anthropic", "meters": [
                {"name": "weekly_all", "used": 80, "pace": 30.0, "elapsed": 50.0,
                 "window_secs": 604800, "resets_at": NOW + half_week}]},
            "openai": {"provider": "openai", "meters": [],
                       "error": "unknown: adapter returned no meters"},
            "meta": {"provider": "meta", "meters": [],
                    "error": "unknown: adapter returned no meters"},
            "xai": {"provider": "xai", "meters": [], "none": True,
                    "none_reason": "no meter", "error": None},
            "google": {"provider": "google", "meters": [], "none": True,
                       "none_reason": "no meter", "error": None},
        }

    def test_picker_ranks_a_meterless_provider_neutrally(self):
        cfg = config.load()
        # every model works but Fable, whose scoped meter this fixture does not report
        cfg["defaults"]["workers"] = [n for n in config.offered(cfg) if n != "fable"]
        providers = self.providers()
        budget, reason = usage.model_budget(cfg, "grok", providers, NOW)
        self.assertEqual((budget, reason), (1.0, None))
        self.assertEqual(usage._budget_label(budget, reason), "1.0 in step")
        order = usage.pick_order(cfg, providers, quiet=True)
        # neutral outranks a provider burning ahead of pace, and a failed probe ranks last
        self.assertEqual(order[0], "grok")
        self.assertEqual(order[-2:], ["astra", "spark"])
        self.assertIn("opus", order)

    def test_picker_ranks_a_failed_meterless_probe_last(self):
        cfg = config.load()
        cfg["defaults"]["workers"] = [n for n in config.offered(cfg) if n != "fable"]
        half_week = 302400
        providers = {
            "anthropic": {"provider": "anthropic", "meters": [
                {"name": "weekly_all", "used": 10, "pace": -40.0, "elapsed": 50.0,
                 "window_secs": 604800, "resets_at": NOW + half_week}]},
            "openai": {"provider": "openai", "meters": [
                {"name": "weekly", "used": 10, "pace": -40.0, "elapsed": 50.0,
                 "window_secs": 604800, "resets_at": NOW + half_week}]},
            "meta": {"provider": "meta", "meters": [
                {"name": "weekly", "used": 10, "pace": -40.0, "elapsed": 50.0,
                 "window_secs": 604800, "resets_at": NOW + half_week}]},
            "xai": {"provider": "xai", "meters": [], "logged_in": False,
                    "error": "unknown: no ~/.grok/auth.json; run 'grok login' once"},
            "google": {"provider": "google", "meters": [], "none": True,
                       "none_reason": "no meter", "error": None},
        }
        order = usage.pick_order(cfg, providers, quiet=True)
        self.assertEqual(order[-1], "grok")


class MeterlessNeverDry(GrokSandbox):
    """The shipped config's real answer: a meterless provider is never exhausted."""

    def providers(self):
        dry = {"used": 100, "pace": 50.0, "elapsed": 50.0,
               "window_secs": 604800, "resets_at": NOW + 302400}
        return {
            "anthropic": {"meters": [{**dry, "name": "weekly_all"},
                                     {**dry, "name": "weekly_scoped"}]},
            "openai": {"meters": [{**dry, "name": "weekly"}]},
            "meta": {"meters": [{**dry, "name": "weekly"}]},
            "xai": {"provider": "xai", "meters": [], "none": True,
                    "none_reason": "no meter", "error": None},
            "google": {"provider": "google", "meters": [], "none": True,
                       "none_reason": "no meter", "error": None},
        }

    def test_a_meterless_worker_never_raises_the_all_dry_quota(self):
        cfg = config.load()   # unscoped: the shipped default, with every model working
        cfg["defaults"]["workers"] = config.offered(cfg)
        providers = self.providers()
        self.assertFalse(usage.model_exhausted(cfg, "grok", providers)[0])
        order = usage.pick_order(cfg, providers, quiet=True)
        self.assertEqual(order, ["grok", "gemini"])
        executor, _ = run.pick_models(cfg, providers, None, "opus", lambda line: None)
        self.assertEqual(executor, "grok")


class ScreenRules(GrokSandbox):
    def test_screen_rules_classify_the_fixture_captures(self):
        for name, state, rule in (
                ("grok-prompt-pane", "at_prompt", "prompt.composer"),
                ("grok-working-pane", "working", "working.turn"),
                ("grok-dialog-pane", "asking", "asking.trust"),
                ("grok-draft-pane", "draft", "prompt.draft"),
                ("grok-suggestion-pane", "at_prompt", "prompt.composer")):
            with self.subTest(name=name):
                pane = (FIX / f"{name}.txt").read_text(encoding="utf-8", errors="replace")
                found = watch.classify("grokbuild", watch.pane_tail(pane), {}, None, {}, NOW)
                self.assertEqual((found["state"], found["rule"]), (state, rule))

    def test_stall_and_auth_panes_answer_in_grok_s_own_words(self):
        stall = (FIX / "grok-stall-pane.txt").read_text()
        mark = watch.stalled_on("grokbuild", watch.pane_tail(stall), "grokbuild",
                                lambda _: None)
        self.assertIn(mark, watch.quotas("grokbuild"))   # the quota policy runs first
        auth = (FIX / "grok-auth-pane.txt").read_text()
        self.assertIsNotNone(watch.auth_expired_on("grokbuild", watch.pane_tail(auth)))

    def test_hook_facts_carry_the_seat_state(self):
        for name, state in (("grok-hook-submit.json", "working"),
                            ("grok-hook-stop.json", "at_prompt")):
            with self.subTest(name=name):
                fact = json.loads((FIX / name).read_text())
                proc = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                                      input=json.dumps(fact), capture_output=True, text=True,
                                      env=self.env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                written = json.loads((self.state / "hook-atoll.json").read_text())
                self.assertEqual(written["event"], fact["hook_event_name"])
                found = watch.hook_state("grokbuild", {**written, "at": NOW})
                self.assertEqual(found[0], state)
        # the camelCase kind the Notification carries: idle_prompt, permission_prompt
        idle = json.loads((FIX / "grok-hook-notification.json").read_text())
        proc = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                              input=json.dumps(idle), capture_output=True, text=True,
                              env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        written = json.loads((self.state / "hook-atoll.json").read_text())
        self.assertEqual(written["kind"], "idle_prompt")
        self.assertEqual(watch.hook_state("grokbuild", {**written, "at": NOW})[0], "at_prompt")
        self.assertEqual(watch.hook_state(
            "grokbuild", {"event": "Notification", "kind": "permission_prompt",
                          "at": NOW})[0], "asking")


class Rulebook(GrokSandbox):
    def test_injected_rulebook_is_byte_identical_to_claude(self):
        claude = subprocess.run([str(REPO / "adapters/claude.sh"), "interactive",
                                 "claude-opus-5", "high"], capture_output=True, text=True,
                                env=self.env)
        self.assertEqual(claude.returncode, 0, claude.stderr)
        cwords = shlex.split(claude.stdout)
        cpath = Path(cwords[cwords.index("--append-system-prompt-file") + 1])
        grok = self.adapter("interactive", "grok-4.7", "xhigh")
        self.assertEqual(grok.returncode, 0, grok.stderr)
        gwords = shlex.split(grok.stdout)
        rules = gwords[gwords.index("--rules") + 1]
        self.assertEqual(rules, cpath.read_text())
        self.assertEqual(rules, (REPO / "orchestrator.md").read_text())
        # and agentkit wrote no harness-specific instruction file anywhere in this HOME
        self.assertFalse((self.grok_home / "GROK.md").exists())
        self.assertEqual([p for p in self.home.rglob("*")
                          if p.suffix in (".md",) and p.name != "prompt.md"
                          and ".agentkit" not in p.parts], [])

    def test_worker_preamble_is_the_shared_one(self):
        self.assertIn("Minimum change that solves the task completely; the best part is no part.",
                      worker.PREAMBLES["executor"])


class HistoryTokens(GrokSandbox):
    def test_history_reads_tokens_from_the_event_stream(self):
        events = FIX / "grok-events.jsonl"
        # 6180 in + 28 out + 12032 cached in + 0 cached out, off the terminal usage
        self.assertEqual(history.event_tokens(events), 18240)
        history.start_run("grok-history")
        for role in ("executor", "reviewer"):
            directory = self.home / role
            directory.mkdir()
            shutil.copy(events, directory / "events.jsonl")
            run.history_role_tokens("grok-history", role, directory)
        row = history.get("grok-history")
        self.assertEqual((row["executor_tokens"], row["reviewer_tokens"]), (18240, 18240))


class StopHook(GrokSandbox):
    def stop(self, message):
        (self.state / "stop-atoll.json").write_text(json.dumps(
            {"session": "atoll", "turn": time.time(), "blocks": 0}))
        fact = json.loads((FIX / "grok-hook-stop.json").read_text())
        fact["lastAssistantMessage"] = message
        proc = subprocess.run(["bash", str(REPO / "hooks/orchestrator-stop.sh")],
                              input=json.dumps(fact), capture_output=True, text=True,
                              env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_stop_hook_reads_the_camelcase_handover(self):
        out = self.stop("ok")
        self.assertIn('"decision": "block"', out)   # no question, no done, no run: back to work
        out = self.stop("May I merge this PR?")
        self.assertNotIn("block", out)


class Wiring(GrokSandbox):
    def test_shipped_config_offers_grok_both_ways(self):
        with (REPO / "config.default.toml").open("rb") as fh:
            cfg = tomllib.load(fh)
        self.assertEqual(cfg["models"]["grok"],
                         {"harness": "grokbuild", "model": "grok-4.7", "effort": "xhigh",
                          "provider": "xai"})
        self.assertEqual(cfg["providers"]["xai"], {"mode": "subscription"})
        self.assertIn("grok", config.offered(cfg))

    def test_no_module_outside_harness_names_grokbuild(self):
        package = REPO / "agentkit/harness"
        for path in sorted((REPO / "agentkit").glob("*.py")):
            with self.subTest(module=path.name):
                self.assertNotIn("grokbuild", path.read_text())
        tree = ast.parse((REPO / "agentkit/usage.py").read_text())
        compared = {node.value
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Compare)
                    for node in node.comparators
                    if isinstance(node, ast.Constant)}
        self.assertNotIn("grokbuild", compared)
        self.assertTrue((package / "grokbuild.py").is_file())

    def test_hooks_install_idempotently(self):
        target = self.grok_home / "hooks/agentkit.json"
        first = self.adapter("hooks")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("wrote seat-state hooks", first.stdout)
        wanted = json.loads(target.read_text())
        self.assertEqual(set(wanted["hooks"]), {"UserPromptSubmit", "Stop", "Notification"})
        stop = wanted["hooks"]["Stop"][0]["hooks"]
        self.assertEqual([entry["command"] for entry in stop],
                         [f"bash {REPO}/hooks/seat-state.sh",
                          f"bash {REPO}/hooks/orchestrator-stop.sh"])
        again = self.adapter("hooks")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("already installed", again.stdout)
        target.write_text("{}\n")   # an older file is backed up once, then replaced
        third = self.adapter("hooks")
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertIn("backed up", third.stdout)
        self.assertEqual(len(list((self.grok_home / "hooks").glob("agentkit.json.bak-*"))), 1)
        self.assertEqual(json.loads(target.read_text()), wanted)


class SpentBalance(GrokSandbox):
    def test_spent_balance_stderr_is_quota(self):
        # A spent SuperGrok week: `grok -p` exits 1 with only this on stderr and
        # no events. It parks the provider and hands the turn over, like any other
        # quota, instead of reading as a transport death three times over.
        stderr = ('Error: Internal error: {   "message": "API error (status 402 '
                  'Payment Required): Grok Build usage balance exhausted", '
                  '  "http_status": 402 }\n')
        out = self.home / "out"
        out.mkdir()
        (out / "prompt.md").write_text("Reply with the single word ok.\n")
        (out / "final.md").write_text("")
        (out / "stderr.log").write_text(stderr)
        (out / "events.jsonl").write_text("")
        for phrase in ("402", "Payment Required", "usage balance exhausted"):
            self.assertIn(phrase, watch.quotas("grokbuild"))
            self.assertIn(phrase, watch.refusals("grokbuild"))
        said = run.harness_said(out, "", "grokbuild")
        self.assertEqual(run.ran_dry(1, said, "grokbuild"), "402")
        self.assertIsNone(run.ran_dry(0, said, "grokbuild"))


if __name__ == "__main__":
    unittest.main()
