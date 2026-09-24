"""OpenCode plugs in as a harness: the adapter's verbs, its screen rules, its tokens.

Offline and deterministic: a stub `opencode` on PATH answers `run`, `session export` and
`auth list` with canned output, every HOME is a temporary directory, and the panes are the
real 2.0.13 captures under tests/fixtures/.  Nothing here contacts a provider -- the one
live proof, a real headless turn through the adapter, is the task's proof command, run by
hand on the host.  Never print or copy a real API key here; the only keys in this file are
the stub's blanks and dummies.
"""

import calendar
from contextlib import ExitStack, redirect_stdout
import datetime
import io
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
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, orch, run, watch  # noqa: E402

ADAPTER = str(REPO / "adapters/opencode.sh")
FIXTURES = REPO / "tests/fixtures"

STUB = """#!/usr/bin/env bash
# canned opencode for tests/test_opencode.py: run cats $STUB_EVENTS and exits $STUB_RC,
# session export cats $STUB_EXPORT, auth list prints $STUB_AUTH_LIST, models cats
# $STUB_MODELS (and fails without one).  Every argv lands in $STUB_ARGV_LOG for the assertions.
[ -n "${STUB_ARGV_LOG:-}" ] && printf '%s\\n' "$*" >>"$STUB_ARGV_LOG"
case "$1" in
  run) cat -- "$STUB_EVENTS"; exit "${STUB_RC:-0}" ;;
  models) cat -- "$STUB_MODELS" ;;
  session) cat -- "$STUB_EXPORT" ;;
  auth) printf '%s' "${STUB_AUTH_LIST:-[]}" ;;
  --version) echo "opencode v9.9.9-test" ;;
  *) echo "stub opencode: $*" >&2; exit 2 ;;
esac
"""

EVENTS_OK = """\
{"type": "step_start", "timestamp": 1, "sessionID": "ses_first", "part": {"type": "step-start"}}
{"type": "text", "timestamp": 2, "sessionID": "ses_first", "part": {"type": "text", "text": "hello"}}
{"type": "step_finish", "timestamp": 3, "sessionID": "ses_first", "part": {"type": "step-finish", "reason": "stop", "tokens": {"input": 90, "output": 8, "reasoning": 2, "cache": {"read": 10, "write": 0}}}}
{"type": "text", "timestamp": 4, "sessionID": "ses_last", "part": {"type": "text", "text": "world"}}
"""

EXPORT_OK = """\
{"info": {"id": "ses_last", "tokens": {"input": 100, "output": 20, "reasoning": 5, "cache": {"read": 50, "write": 0}}}}
"""

EVENTS_AUTH_ERROR = """\
{"type": "step_start", "timestamp": 1, "sessionID": "ses_bad", "part": {"type": "step-start"}}
{"type": "error", "timestamp": 2, "sessionID": "ses_bad", "error": {"type": "provider.auth", "message": "Invalid API Key", "status": 401}}
"""


class OpenCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".opencode-", dir=REPO)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "opencode").write_text(STUB)
        (self.bin / "opencode").chmod(0o755)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
                    "AGENTKIT_SESSION": "fakesession"}
        self.cfgdir = self.home / ".config" / "opencode"
        self.argv_log = self.root / "argv.log"

    def adapter(self, *args, **kwargs):
        env = dict(self.env)
        env.update(kwargs.pop("env", {}))
        return subprocess.run([ADAPTER, *args], capture_output=True, text=True,
                              env=env, **kwargs)

    def write_config(self, key):
        self.cfgdir.mkdir(parents=True, exist_ok=True)
        (self.cfgdir / "opencode.json").write_text(json.dumps(
            {"provider": {"mimo": {"options": {"apiKey": key}}}}))

    # A fake `curl` beside the stub `opencode`: each console call is answered from
    # the `resp-<call>` file the test writes -- the code on the first line, the body
    # on the rest, 000 with no body where no file is -- and a CDP tab creation
    # from `resp-cdp-new`, so no usage test reaches a real endpoint or browser.
    # Every URL probed and every header line sent are appended to `asked-url`
    # and `asked-hdr`, under $HOME/fake beside the temp HOME.
    FAKE_CURL = """#!/bin/sh
dir="$HOME/fake"
url=""; hf=""; prev=""
for a in "$@"; do
  case "$a" in
    *json/new*)
      printf 'PUT %s\\n' "$a" >>"$dir/asked-url"
      f="$dir/resp-cdp-new"; [ -f "$f" ] || exit 7; cat "$f"; exit 0 ;;
  esac
  if [ "$prev" = "-H" ]; then case "$a" in @*) hf=${a#@};; esac; fi
  case "$a" in https://*) url=$a; printf '%s\\n' "$a" >>"$dir/asked-url";; esac
  prev=$a
done
[ -n "$hf" ] && cat "$hf" >>"$dir/asked-hdr"
name=$(printf '%s' "$url" | sed 's|.*/api/v1/||; s|/|_|g')
resp="$dir/resp-$name"
[ -f "$resp" ] || { printf '\\n000\\n'; exit 0; }
code=$(sed -n '1p' "$resp"); body=$(sed -n '2,$p' "$resp")
printf '%s\\n%s\\n' "$body" "$code"
"""

    # A fake bridge venv python beside the fake curl: it records its argv and
    # answers `eval` from the `bridge-eval` file -- but only once a tab is
    # selected, the way the real bridge refuses without one, and failing the
    # first `fail-evals` rounds outright, the way a navigating tab destroys its
    # round.
    FAKE_VENV = """#!/bin/sh
dir="$HOME/fake"
printf '%s\\n' "$*" >>"$dir/asked-bridge"
if [ -f "$dir/fail-evals" ]; then
  n=$(cat "$dir/fail-evals")
  if [ "$n" -gt 0 ] 2>/dev/null; then echo $((n - 1)) >"$dir/fail-evals"; exit 1; fi
fi
sel="$HOME/.local/share/browser-bridge/selections/agentkit-mimo-usage.json"
[ -f "$sel" ] || { echo "bridge: No selected tab" >&2; exit 1; }
cat "$dir/bridge-eval"
"""

    def fake_curl(self):
        fake = self.home / "fake"
        fake.mkdir(exist_ok=True)
        (self.bin / "curl").write_text(self.FAKE_CURL)
        (self.bin / "curl").chmod(0o755)

    def fake_bridge(self):
        """A bridge of scripts under the temp HOME: nothing real answers."""
        bridge = self.home / ".local/share/browser-bridge"
        (bridge / "venv/bin").mkdir(parents=True)
        (bridge / "bridge.py").write_text("# fake bridge for tests/test_opencode.py\n")
        venv = bridge / "venv/bin/python"
        venv.write_text(self.FAKE_VENV)
        venv.chmod(0o755)

    def answer(self, call, code, body=""):
        """What the console says to one call: the code, then the body."""
        (self.home / "fake" / f"resp-{call}").write_text(f"{code}\n{body}\n")

    def bridge_answer(self, payload):
        """What the remembered tab's fetch round says, as the bridge prints it."""
        (self.home / "fake" / "bridge-eval").write_text(json.dumps(json.dumps(payload)))

    def bridge_payload(self):
        """The logged-in tab's answer, built from the console fixtures."""
        usage = json.loads((FIXTURES / "mimo-tokenplan-usage.json").read_text())
        detail = json.loads((FIXTURES / "mimo-tokenplan-detail.json").read_text())
        return {"ok": True, "usage": usage["data"], "detail": detail["data"],
                "host": "platform.xiaomimimo.com"}

    def preselect_tab(self, target="fixture-remembered"):
        """A console tab the bridge already remembers, from an earlier probe."""
        selections = self.home / ".local/share/browser-bridge/selections"
        selections.mkdir(parents=True, exist_ok=True)
        (selections / "agentkit-mimo-usage.json").write_text(
            json.dumps({"target_id": target}))

    def asked_urls(self):
        """Every URL the console API was probed at, in order."""
        try:
            return (self.home / "fake" / "asked-url").read_text().splitlines()
        except OSError:
            return []

    def asked_bridge(self):
        """Every bridge invocation's argv, in order."""
        try:
            return (self.home / "fake" / "asked-bridge").read_text().splitlines()
        except OSError:
            return []

    def asked_headers(self):
        """Every header line the probes went out with, in order."""
        try:
            return (self.home / "fake" / "asked-hdr").read_text()
        except OSError:
            return ""

    def plan_meters(self):
        """The three meters the console fixtures read as: plan and compensation
        reset at the fixture period end, the month counter at month end."""
        reset = calendar.timegm((2026, 10, 22, 23, 59, 59))
        now = datetime.datetime.now(datetime.timezone.utc)
        start = calendar.timegm((now.year, now.month, 1, 0, 0, 0))
        if now.month == 12:
            mend = calendar.timegm((now.year + 1, 1, 1, 0, 0, 0))
        else:
            mend = calendar.timegm((now.year, now.month + 1, 1, 0, 0, 0))
        return [("plan", 6.0, reset, 2592000),
                ("compensation", 5.0, reset, 2592000),
                ("month", 34.8, mend, mend - start)]

    def pane(self, kind):
        return (FIXTURES / f"opencode-{kind}-pane.txt").read_text()

    def decide(self, kind, fact=None):
        return watch.classify("opencode", watch.pane_tail(self.pane(kind)), fact,
                              None, {}, time.time())

    # --- run ---------------------------------------------------------------
    def test_run_writes_final_session_tokens_and_usage(self):
        rundir = self.root / "runs" / "rid1"
        out = rundir / "round-1" / "executor"
        out.mkdir(parents=True)
        (rundir / "run.json").write_text("{}")
        prompt = self.root / "prompt.md"
        prompt.write_text("say hello\n")
        events = self.root / "events.jsonl"
        events.write_text(EVENTS_OK)
        export = self.root / "export.json"
        export.write_text(EXPORT_OK)
        proc = self.adapter("run", "mimo/mimo-v2.6-pro", "high", str(self.root),
                            str(prompt), str(out),
                            env={"STUB_EVENTS": str(events), "STUB_EXPORT": str(export),
                                 "STUB_ARGV_LOG": str(self.argv_log)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((out / "final.md").read_text(), "hello\nworld\n")
        self.assertEqual((out / "session_id").read_text(), "ses_last")
        argv = self.argv_log.read_text()
        self.assertIn("-m mimo/mimo-v2.6-pro#high", argv)
        self.assertIn("--title rid1/executor", argv)
        self.assertIn("--standalone", argv)
        self.assertIn("--auto", argv)
        lines = (out / "events.jsonl").read_text().splitlines()
        usage = json.loads(lines[-1])
        self.assertEqual(usage["type"], "result")
        # output_tokens folds reasoning in: OpenCode counts the two apart
        self.assertEqual(usage["usage"], {"input_tokens": 100, "output_tokens": 25,
                                         "cache_read_input_tokens": 50,
                                         "cache_creation_input_tokens": 0})

    def test_run_resume_passes_session_and_failure_mirrors_error(self):
        out = self.root / "out"
        out.mkdir()
        prompt = self.root / "prompt.md"
        prompt.write_text("hi\n")
        events = self.root / "events.jsonl"
        events.write_text(EVENTS_AUTH_ERROR)
        proc = self.adapter("run", "mimo/mimo-v2.6-pro", "high", str(self.root),
                            str(prompt), str(out), "ses_bad",
                            env={"STUB_EVENTS": str(events), "STUB_RC": "1",
                                 "STUB_ARGV_LOG": str(self.argv_log),
                                 "STUB_EXPORT": str(self.root / "missing.json")})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--session ses_bad", self.argv_log.read_text())
        self.assertEqual((out / "final.md").read_text(), "")
        self.assertEqual((out / "session_id").read_text(), "ses_bad")
        # the failure is said in the event log, and mirrored to stderr where the auth
        # watch reads; with no export there is no usage line to count
        self.assertIn("Invalid API Key", (out / "stderr.log").read_text())
        logged = (out / "events.jsonl").read_text()
        self.assertIn('"type": "error"', logged)
        self.assertNotIn('"type": "result"', logged)
        self.assertIsNone(history.event_tokens(out / "events.jsonl"))

    def test_run_at_none_passes_the_bare_model_and_any_other_effort_its_variant(self):
        prompt = self.root / "prompt.md"
        prompt.write_text("hi\n")
        events = self.root / "events.jsonl"
        events.write_text(EVENTS_OK)
        for effort, model in (("none", "mimo/mimo-v2.6-pro"), ("high", "mimo/mimo-v2.6-pro#high")):
            self.argv_log.unlink(missing_ok=True)
            proc = self.adapter("run", "mimo/mimo-v2.6-pro", effort, str(self.root),
                                str(prompt), str(self.root / f"out-{effort}"),
                                env={"STUB_EVENTS": str(events), "STUB_ARGV_LOG": str(self.argv_log),
                                     "STUB_EXPORT": str(self.root / "missing.json")})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            words = self.argv_log.read_text().splitlines()[0].split()
            self.assertEqual(words[words.index("-m") + 1], model)
            # and the seat is pinned to the same model
            proc = self.adapter("interactive", "mimo/mimo-v2.6-pro", effort)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            content = next(word for word in shlex.split(proc.stdout)
                           if word.startswith("OPENCODE_CONFIG_CONTENT=")).split("=", 1)[1]
            self.assertEqual(json.loads(content)["model"], model)

    # --- interactive ---------------------------------------------------------
    def test_interactive_rulebook_is_byte_identical_to_claude(self):
        proc = self.adapter("interactive", "mimo/mimo-v2.6-pro", "high")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        words = shlex.split(proc.stdout)
        content = next(word for word in words
                       if word.startswith("OPENCODE_CONFIG_CONTENT=")).split("=", 1)[1]
        config_doc = json.loads(content)
        # the model with the effort as its variant, the seat plugin beside the rulebook
        self.assertEqual(config_doc["model"], "mimo/mimo-v2.6-pro#high")
        self.assertEqual(config_doc["plugins"], [str(REPO / "hooks/opencode-seat")])
        injected = config_doc["agents"]["build"]["system"].encode()
        claude = subprocess.run(
            [str(REPO / "adapters/claude.sh"), "interactive", "opus", "xhigh"],
            capture_output=True, text=True, env=self.env)
        self.assertEqual(claude.returncode, 0, claude.stderr)
        cwords = shlex.split(claude.stdout)
        rulebook = cwords[cwords.index("--append-system-prompt-file") + 1]
        self.assertEqual(injected, Path(rulebook).read_bytes())

    def test_interactive_resumes_and_refuses_a_launcher_id(self):
        proc = self.adapter("interactive", "mimo/mimo-v2.6-pro", "high", "ses_123")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--session ses_123", proc.stdout)
        proc = self.adapter("interactive", "mimo/mimo-v2.6-pro", "high", "launched-id", "new")
        self.assertEqual(proc.returncode, 3)

    # --- auth, usage, install, login, hooks ----------------------------------
    def test_auth_reports_key_presence_and_absence(self):
        self.write_config("tp-dummy")
        proc = self.adapter("auth")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(proc.stdout.splitlines()), 1)
        proc = self.adapter("auth", "seat")
        self.assertEqual(proc.returncode, 0)
        self.write_config("")
        proc = self.adapter("auth")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(proc.stderr.splitlines()), 1)
        # and the auth store beside the config answers when the config has no key
        proc = self.adapter("auth", env={"STUB_AUTH_LIST": '[{"id": "mimo"}]'})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("auth store", proc.stdout)
        # missing jq cannot read the config, but a saved login is still a yes
        self.write_config("tp-dummy")
        # jq lives in /bin and /usr/bin. A bash on this PATH, and nothing else,
        # is what lets the adapter and the stub start without finding jq.
        (self.bin / "bash").symlink_to(shutil.which("bash"))
        bare = str(self.bin)
        proc = self.adapter("auth", env={"PATH": bare,
                                         "STUB_AUTH_LIST": '[{"id": "mimo"}]'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("auth store", proc.stdout)
        proc = self.adapter("auth", env={"PATH": bare})
        self.assertEqual(proc.returncode, 2)

    def test_usage_reports_none_with_reason(self):
        # no key is a failed probe: an unauthenticated account must not rank neutral
        self.write_config("")
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual(usage["provider"], "mimo")
        self.assertEqual(usage["meters"], [])
        self.assertIn("is missing", usage["error"])
        self.assertNotIn("none", usage)
        # a configured key and no meter source is [usage] none, with the reason
        self.write_config("tp-dummy")
        self.fake_curl()
        self.fake_bridge()
        self.preselect_tab()
        self.bridge_answer({"ok": False, "stage": "usage", "http": 401,
                            "code": 401, "host": "platform.xiaomimimo.com"})
        self.answer("tokenPlan_usage", 401,
                    (FIXTURES / "mimo-401.json").read_text())
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual((usage["provider"], usage["meters"], usage["error"]),
                         ("mimo", [], None))
        self.assertIn("no meter", usage["none"])
        self.assertIn("platform.xiaomimimo.com/console/plan-manage", usage["none"])

    def test_usage_reads_plan_meters_from_the_browser_session(self):
        # The remembered console tab's fetch round: every item the plan has
        # becomes a meter, plan and compensation resetting at the fixture
        # period end, the month counter at month end.  The fixtures mirror the
        # console's real response shape -- envelope and field names read off
        # the live API's own answers and the bundle it serves, values invented
        # -- and the bridge is scripts: no live call, and nothing real leaves
        # the temp HOME.
        self.write_config("tp-dummy")
        self.fake_curl()
        self.fake_bridge()
        self.preselect_tab()
        self.bridge_answer(self.bridge_payload())
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual(usage["provider"], "mimo")
        self.assertIsNone(usage["error"])
        self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                          for m in usage["meters"]],
                         self.plan_meters())
        self.assertNotIn("none", usage)
        # one fetch round in the remembered tab, and curl never asked: the tab
        # already stood, so no tab was created and the key was never tried
        self.assertEqual(len(self.asked_bridge()), 1)
        self.assertIn("eval", self.asked_bridge()[0])
        self.assertEqual(self.asked_urls(), [])

    def test_usage_opens_a_console_tab_when_the_browser_has_none(self):
        # No remembered tab: the first fetch round fails, a console tab is
        # created over CDP and remembered the bridge's own way, and the second
        # round reads the meters off it.
        self.write_config("tp-dummy")
        self.fake_curl()
        self.fake_bridge()
        self.bridge_answer(self.bridge_payload())
        (self.home / "fake" / "resp-cdp-new").write_text(
            json.dumps({"id": "fixture-target"}))
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                          for m in usage["meters"]],
                         self.plan_meters())
        self.assertNotIn("none", usage)
        self.assertEqual(self.asked_urls(),
                         ["PUT http://127.0.0.1:9222/json/new?"
                          "https://platform.xiaomimimo.com/console/plan-manage"])
        remembered = json.loads(
            (self.home / ".local/share/browser-bridge/selections"
             / "agentkit-mimo-usage.json").read_text())
        self.assertEqual(remembered, {"target_id": "fixture-target"})
        self.assertEqual(len(self.asked_bridge()), 2)   # eval, eval

    def test_usage_replaces_a_remembered_tab_that_is_gone(self):
        # The remembered tab was reaped: the first round fails, the stale
        # selection is dropped for a console tab created over CDP, and the
        # second round reads the meters off it.
        self.write_config("tp-dummy")
        self.fake_curl()
        self.fake_bridge()
        self.preselect_tab(target="fixture-reaped")
        self.bridge_answer(self.bridge_payload())
        (self.home / "fake" / "fail-evals").write_text("1\n")
        (self.home / "fake" / "resp-cdp-new").write_text(
            json.dumps({"id": "fixture-target"}))
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                          for m in usage["meters"]],
                         self.plan_meters())
        self.assertNotIn("none", usage)
        self.assertEqual(len(self.asked_urls()), 1)
        self.assertIn("json/new?", self.asked_urls()[0])
        remembered = json.loads(
            (self.home / ".local/share/browser-bridge/selections"
             / "agentkit-mimo-usage.json").read_text())
        self.assertEqual(remembered, {"target_id": "fixture-target"})
        self.assertEqual(len(self.asked_bridge()), 2)   # eval, eval

    def test_usage_fetches_again_when_navigation_destroys_the_round(self):
        # A fresh tab still navigating destroys the round that lands in it:
        # the probe fetches once more instead of reporting the bridge down.
        self.write_config("tp-dummy")
        self.fake_curl()
        self.fake_bridge()
        self.bridge_answer(self.bridge_payload())
        (self.home / "fake" / "fail-evals").write_text("2\n")
        (self.home / "fake" / "resp-cdp-new").write_text(
            json.dumps({"id": "fixture-target"}))
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual(len(usage["meters"]), 3)
        self.assertNotIn("none", usage)
        self.assertEqual(len(self.asked_bridge()), 3)   # eval, eval, eval

    def test_usage_reads_plan_meters_from_the_provider_key(self):
        # No bridge at all: the provider key is tried against the same two
        # console calls, and code-0 answers are meters the same way.  (The
        # live API refuses the key with 401 today; this is the shape an
        # accepted key would take.)
        self.write_config("tp-dummy")
        self.fake_curl()
        self.answer("tokenPlan_usage", 200,
                    (FIXTURES / "mimo-tokenplan-usage.json").read_text())
        self.answer("tokenPlan_detail", 200,
                    (FIXTURES / "mimo-tokenplan-detail.json").read_text())
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual([(m["name"], m["used"], m["resets_at"], m["window_secs"])
                          for m in usage["meters"]],
                         self.plan_meters())
        self.assertNotIn("none", usage)
        self.assertEqual(self.asked_urls(),
                         ["https://platform.xiaomimimo.com/api/v1/tokenPlan/usage",
                          "https://platform.xiaomimimo.com/api/v1/tokenPlan/detail"])
        self.assertIn("Authorization: Bearer tp-dummy", self.asked_headers())

    def test_usage_prefers_the_browser_session_over_the_key(self):
        # Both sources would answer: the browser session wins and the key is
        # never tried -- curl is never asked at all.
        self.write_config("tp-dummy")
        self.fake_curl()
        self.fake_bridge()
        self.preselect_tab()
        self.bridge_answer(self.bridge_payload())
        self.answer("tokenPlan_usage", 200,
                    (FIXTURES / "mimo-tokenplan-usage.json").read_text())
        self.answer("tokenPlan_detail", 200,
                    (FIXTURES / "mimo-tokenplan-detail.json").read_text())
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual(len(usage["meters"]), 3)
        self.assertEqual(self.asked_urls(), [])
        self.assertEqual(self.asked_headers(), "")

    def test_usage_reports_none_naming_every_source_tried(self):
        # Every source tried and none a meter: the remembered tab's session is
        # refused (401), no mimo CLI answers, and the key is refused (401).
        # The reason names each source and says exactly where to log in.
        self.write_config("tp-dummy")
        self.fake_curl()
        self.fake_bridge()
        self.preselect_tab()
        self.bridge_answer({"ok": False, "stage": "usage", "http": 401,
                            "code": 401, "host": "platform.xiaomimimo.com"})
        refused = (FIXTURES / "mimo-401.json").read_text()
        self.answer("tokenPlan_usage", 401, refused)
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual((usage["provider"], usage["meters"], usage["error"]),
                         ("mimo", [], None))
        for word in ("no meter", "browser", "mimo", "401",
                     "platform.xiaomimimo.com/console/plan-manage",
                     "ak browser login"):
            self.assertIn(word, usage["none"])
        # the refused tab answers for the browser, so curl goes out once, for
        # the key; a refused usage call is never followed by a detail call
        self.assertEqual(len(self.asked_bridge()), 1)
        self.assertEqual(self.asked_urls(),
                         ["https://platform.xiaomimimo.com/api/v1/tokenPlan/usage"])
        # and a tab a login elsewhere left behind is moved to the console in
        # place, while this round still says the login itself is missing
        self.bridge_answer({"ok": False, "stage": "usage", "http": 404,
                            "host": "account.xiaomi.com"})
        (self.home / "fake" / "asked-bridge").unlink()
        (self.home / "fake" / "asked-url").unlink()
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual((usage["meters"], usage["error"]), ([], None))
        self.assertIn("no Xiaomi login", usage["none"])
        self.assertIn("platform.xiaomimimo.com/console/plan-manage", usage["none"])
        self.assertIn("location.href", self.asked_bridge()[-1])
        self.assertEqual(self.asked_urls(),
                         ["https://platform.xiaomimimo.com/api/v1/tokenPlan/usage"])

    def test_usage_ignores_a_meterless_mimo_cli(self):
        # A mimo CLI that answers no meter-shaped JSON is tried and passed
        # over, never trusted as the plan: the key attempt behind it decides.
        self.write_config("tp-dummy")
        (self.bin / "mimo").write_text("#!/bin/sh\necho 'mimo: no such command'\n")
        (self.bin / "mimo").chmod(0o755)
        self.fake_curl()
        self.answer("tokenPlan_usage", 401,
                    (FIXTURES / "mimo-401.json").read_text())
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual((usage["meters"], usage["error"]), ([], None))
        self.assertIn("mimo", usage["none"])
        self.assertEqual(self.asked_urls(),
                         ["https://platform.xiaomimimo.com/api/v1/tokenPlan/usage"])
        # one answering the adapter's own meter shape is meters, and the
        # console is never asked: the CLI stands ahead of the key
        (self.bin / "mimo").write_text("#!/bin/sh\n"
            "printf '%s' '{\"meters\":[{\"name\":\"plan\",\"used\":12,"
            "\"resets_at\":1999999999,\"window_secs\":2592000}]}'\n")
        (self.home / "fake" / "asked-url").unlink()
        proc = self.adapter("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        usage = json.loads(proc.stdout)
        self.assertEqual(usage["meters"],
                         [{"name": "plan", "used": 12,
                           "resets_at": 1999999999, "window_secs": 2592000}])
        self.assertNotIn("none", usage)
        self.assertEqual(self.asked_urls(), [])

    def test_install_login_hooks_verbs(self):
        proc = self.adapter("install")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("already installed", proc.stdout)
        self.write_config("tp-dummy")
        proc = self.adapter("login", stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("already logged in", proc.stdout)
        self.write_config("")
        proc = self.adapter("login", stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("opencode auth login", proc.stderr)
        proc = self.adapter("hooks")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("nothing to write", proc.stdout)

    # --- screen --------------------------------------------------------------
    def test_screen_rules_read_the_captures(self):
        self.assertEqual(self.decide("prompt")["state"], "at_prompt")
        self.assertEqual(self.decide("prompt")["authority"], "screen")
        self.assertEqual(self.decide("working")["state"], "working")
        self.assertEqual(self.decide("dialog")["state"], "asking")
        # a failed turn is still a prompt: `Error: ` is a stall word, not a state
        self.assertEqual(self.decide("auth")["state"], "at_prompt")

    def test_stall_and_auth_panes_answer_in_opencode_s_own_words(self):
        stall = self.pane("stall")
        mark = watch.stalled_on("opencode", watch.pane_tail(stall), "opencode",
                                lambda _: None)
        self.assertIn(mark, watch.quotas("opencode"))   # the quota policy runs first
        auth = self.pane("auth")
        self.assertIsNotNone(watch.auth_expired_on("opencode", watch.pane_tail(auth)))

    def test_the_status_line_under_an_error_hides_neither_signature(self):
        # as captured, and as 2.0.14 draws a turn that never completed: with no duration
        for status in ("Build · mimo-v2.6-pro · 166ms", "Build · mimo-v2.6-pro"):
            with self.subTest(status=status):
                auth = self.pane("auth").replace("Build · mimo-v2.6-pro · 166ms", status)
                self.assertIn(status, auth)
                self.assertEqual(watch.auth_expired_on("opencode", auth), "Invalid API Key")
                stall = self.pane("stall").replace("Build · mimo-v2.6-pro · 166ms", status)
                self.assertEqual(watch.stalled_on("opencode", stall, "opencode", self.fail),
                                 "429")

    def test_hook_facts_decide_and_yield_to_the_dialog(self):
        now = time.time()
        stop = {"session": "seat", "event": "Stop", "kind": "", "text": "", "at": now}
        found = self.decide("prompt", stop)
        self.assertEqual((found["state"], found["authority"]), ("at_prompt", "hook"))
        begun = {"session": "seat", "event": "UserPromptSubmit", "kind": "",
                 "text": "do it", "at": now}
        # no rule on a bare transcript tail, so the hook decides the turn is running; the
        # finished-turn footer stays out of it, since it reads as a prompt rule of its own now
        transcript = "     ok\n\n     still streaming"
        found = watch.classify("opencode", transcript, begun, None, {}, now)
        self.assertEqual((found["state"], found["authority"]), ("working", "hook"))
        # but a rule that positively names another state overrides a stale hook fact
        found = self.decide("prompt", begun)
        self.assertEqual((found["state"], found["authority"]), ("at_prompt", "screen"))
        self.assertEqual(found["hooked"], "working")
        found = self.decide("dialog", stop)
        self.assertEqual((found["state"], found["authority"]), ("asking", "screen"))
        self.assertEqual(found["hooked"], "at_prompt")

    # --- history ---------------------------------------------------------------
    def test_history_counts_opencode_tokens(self):
        out = self.root / "executor"
        out.mkdir()
        (out / "events.jsonl").write_text(
            EVENTS_OK
            + json.dumps({"type": "result", "sessionID": "ses_last",
                          "usage": {"input_tokens": 100, "output_tokens": 25,
                                    "cache_read_input_tokens": 50,
                                    "cache_creation_input_tokens": 0}}) + "\n")
        retry = self.root / "executor-retry1"
        retry.mkdir()
        (retry / "events.jsonl").write_text(
            json.dumps({"type": "result",
                        "usage": {"input_tokens": 10, "output_tokens": 5}}) + "\n")
        self.assertEqual(history.event_tokens(out / "events.jsonl"), 175)
        with patch.object(config, "HOME", self.home):
            history.start_run("r1")
            run.history_role_tokens("r1", "executor", out)
            row = history.get("r1")
        self.assertEqual(row["executor_tokens"], 190)

    def test_step_tokens_alone_report_nothing(self):
        # OpenCode streams per-step tokens on tool turns and none at all on trivial ones;
        # neither is counted.  The adapter appends the session's own totals as the `result`
        # record, and that line alone is what history reads, so a turn is never half
        # counted from its steps and never counted twice.
        out = self.root / "executor"
        out.mkdir()
        (out / "events.jsonl").write_text(EVENTS_OK)
        self.assertIsNone(history.event_tokens(out / "events.jsonl"))

    # --- compact ---------------------------------------------------------------
    def test_compact_stamp_from_handed_tokens(self):
        state = self.root / "stamp.json"
        env = dict(self.env, AK_RUN_ROLE="seat", IDLE_COMPACT_STATE=str(state))
        payload = json.dumps({"hook_event_name": "Stop", "session_id": "ses_last",
                              "context_tokens": 12832})
        proc = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                              input=payload, capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0)
        stamp = json.loads(state.read_text())
        self.assertEqual(stamp["context_tokens"], 12832)
        self.assertEqual(stamp["session_id"], "ses_last")
        # zero is not a size: nothing is stamped and the last good one stands
        state.unlink()
        payload = json.dumps({"hook_event_name": "Stop", "context_tokens": 0})
        proc = subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")],
                              input=payload, capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(state.exists())

    def test_plugin_translates_lifecycle_events(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is required to load the OpenCode plugin")
        # ESM pinned, not auto-detected: without it an older Node fails the plugin.
        pkg = json.loads((REPO / "hooks/opencode-seat/package.json").read_text())
        self.assertEqual(pkg.get("type"), "module")
        events = [
            {"type": "session.idle", "data": {}},
            {"type": "session.inbox.enqueued", "data": {
                "item": {"type": "user", "payload": {"text": "do the thing"}}}},
            {"type": "session.step.ended", "data": {
                "sessionID": "ses_plug",
                "tokens": {"input": 10, "output": 4, "reasoning": 1,
                           "cache": {"read": 2, "write": 3}}}},
            {"type": "session.execution.succeeded", "data": {"sessionID": "ses_plug"}},
            {"type": "permission.asked", "data": {
                "action": "bash", "resources": ["ls", 7]}},
        ]
        driver = r"""
import { pathToFileURL } from "node:url";
const { seatFact } = await import(pathToFileURL(process.argv[1]).href);
const events = JSON.parse(process.argv[2]);
const steps = new Map();
const facts = [];
for (const event of events) {
  const fact = seatFact(event, steps);
  if (fact) facts.push(fact);
}
console.log(JSON.stringify(facts));
"""
        plugin = str(REPO / "hooks/opencode-seat/index.js")
        proc = subprocess.run(
            [node, "--input-type=module", "-e", driver, plugin, json.dumps(events)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        facts = json.loads(proc.stdout)
        self.assertEqual(facts, [
            {"hook_event_name": "UserPromptSubmit", "message": "do the thing"},
            {"hook_event_name": "Stop", "session_id": "ses_plug", "context_tokens": 20},
            {"hook_event_name": "PermissionRequest", "tool_name": "bash", "message": "bash ls"},
        ])

    # --- the session a seat comes back to ----------------------------------------
    def run_plugin(self, receipt, events, parents):
        """The seat plugin, loaded the way OpenCode loads it, on a stream of these events.

        `parents` is OpenCode's own record of each session: its parent, None for none, and a
        session it does not name is one whose record cannot be read.
        """
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is required to load the OpenCode plugin")
        driver = r"""
import { pathToFileURL } from "node:url";
const plugin = (await import(pathToFileURL(process.argv[1]).href)).default;
const events = JSON.parse(process.argv[2]);
const parents = JSON.parse(process.argv[3]);
let done;
const drained = new Promise((resolve) => { done = resolve; });
const session = { get: async ({ sessionID }) => {
  if (!(sessionID in parents)) throw new Error(`no session ${sessionID}`);
  return { id: sessionID, ...(parents[sessionID] ? { parentID: parents[sessionID] } : {}) };
} };
const ctx = { session, event: { subscribe: async function* () { yield* events; done(); } } };
const stop = await plugin.setup(ctx);
await drained;
stop();
"""
        env = dict(self.env, AGENTKIT_SESSION="",
                   AGENTKIT_OPENCODE_RECEIPT=str(receipt))
        proc = subprocess.run(
            [node, "--input-type=module", "-e", driver,
             str(REPO / "hooks/opencode-seat/index.js"), json.dumps(events), json.dumps(parents)],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    @staticmethod
    def event(kind, sid):
        """One OpenCode 2.0.14 event, shaped the way a seat's plugin is handed it."""
        data = {"sessionID": sid}
        if kind == "session.inbox.enqueued":
            data.update(inboxID="msg_1", item={"type": "user", "payload": {"text": "go"}})
        return {"type": kind, "data": data}

    def turn(self, sid):
        return [self.event(kind, sid) for kind in ("session.inbox.enqueued",
                                                   "session.execution.started",
                                                   "session.execution.succeeded")]

    def test_plugin_keeps_the_seat_s_own_session_in_its_receipt(self):
        receipt = self.root / "receipt"
        receipt.mkdir()
        kept = receipt / "session"
        parents = {"ses_seat": None, "ses_sub": "ses_seat", "ses_new": None}
        seat, sub = self.turn("ses_seat"), self.turn("ses_sub")
        # a subagent the seat starts, ending before its turn, after it, or started while the
        # seat is idle: OpenCode's own record names its parent, and it is never written
        for order in ([*seat[:2], *sub, seat[2]], [*seat[:2], *sub[:2], seat[2], sub[2]],
                      [*seat, *sub]):
            with self.subTest(order=[event["data"]["sessionID"] for event in order]):
                kept.unlink(missing_ok=True)
                self.run_plugin(receipt, order, parents)
                self.assertEqual(kept.read_text(), "ses_seat")
        # a session of the seat's own, prompted while another turn still runs, is the one it
        # comes back to from that prompt on, however the older turn ends meanwhile
        self.run_plugin(receipt, [*seat[:2], *self.turn("ses_new")[:2], seat[2]], parents)
        self.assertEqual(kept.read_text(), "ses_new")
        # a write that fails, and a session whose record cannot be read, leave the last good id
        (receipt / "session.next").mkdir()
        self.run_plugin(receipt, seat, parents)
        (receipt / "session.next").rmdir()
        self.run_plugin(receipt, self.turn("ses_unknown"), parents)
        self.assertEqual(kept.read_text(), "ses_new")
        # a receipt the seat's stop removed is never made again by a late fact
        gone = self.root / "gone"
        self.run_plugin(gone, seat, parents)
        self.assertFalse(gone.exists())

    def test_a_dead_seat_comes_back_on_its_own_session(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            **self.env, "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(self.root / "sockets"), "AGENTKIT_DISCORD_WEBHOOK": "off"}))
        os.environ.pop(config.ADAPTER_DIR_ENV, None)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, self.home / ".agentkit" / key.lower()))
        config.ensure_dirs()
        launched = []
        # tmux has lost every seat -- a reboot -- and nothing here starts one for real
        stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        stack.enter_context(patch.object(orch, "start", side_effect=lambda name, cwd, cmd, model:
                                         launched.append((name, cmd))))
        cfg = config.load()
        cwd = self.root / "one directory"
        cwd.mkdir()
        # two seats in one directory, each opened with no id, and beta's session the latest
        for name, sid in (("alpha", "ses_alpha"), ("beta", "ses_beta")):
            config.save_session(cfg, name, "mimo", ["mimo"], {"cwd": str(cwd)})
            orch.launch(name, "mimo", cwd, ["opencode"], None)
            cmd = launched[-1][1]
            self.assertEqual(cmd[0], "env")
            receipt = Path(cmd[1].split("=", 1)[1])
            self.assertTrue(cmd[1].startswith("AGENTKIT_OPENCODE_RECEIPT="))
            self.assertEqual(list(receipt.iterdir()), [])
            self.run_plugin(receipt, self.turn(sid), {sid: None})
        for name, sid, other in (("alpha", "ses_alpha", "ses_beta"),
                                 ("beta", "ses_beta", "ses_alpha")):
            with self.subTest(seat=name):
                self.assertTrue(orch.resumable(orch.records()[name]))
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(orch.resume(cfg, name, log=lambda _: None,
                                                 dry_run=True), 0)
                words = shlex.split(out.getvalue())
                self.assertEqual(words[words.index("--session") + 1], sid)
                self.assertNotIn(other, words)
                # reopened for real, the new launch's receipt holds the session from the start,
                # so a seat that dies again before its next turn still comes back to it
                before = orch.records()[name]["opencode_launch"]
                self.assertEqual(orch.resume(cfg, name, log=lambda _: None, hand_over=False),
                                 "resumed")
                record = orch.records()[name]
                self.assertNotEqual(record["opencode_launch"], before)
                self.assertFalse((config.STATE / f"opencode-launch-{before}").exists())
                words = launched[-1][1]
                self.assertEqual(words[words.index("--session") + 1], sid)
                self.assertEqual(orch.seat_conversation(record), sid)
        # each seat's current receipt, and nothing of the launches before
        self.assertEqual({path.name for path in config.STATE.glob("opencode-launch-*")},
                         {f"opencode-launch-{orch.records()[name]['opencode_launch']}"
                          for name in ("alpha", "beta")})

    # --- models ------------------------------------------------------------------
    def models(self, **env):
        proc = self.adapter("models", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [line.split("\t") for line in proc.stdout.splitlines()]

    def test_a_live_listing_gives_mimo_no_effort_and_leaves_an_unknown_id_unsaid(self):
        listing = self.root / "models.txt"
        listing.write_text("mimo/mimo-v2.6-flash\nmimo/mimo-v2.6-pro\nopencode/big-pickle\n")
        self.assertEqual(self.models(STUB_MODELS=str(listing)), [
            ["mimo/mimo-v2.6-flash", "MiMo V2.6 Flash", "none"],
            ["mimo/mimo-v2.6-pro", "MiMo V2.6 Pro", "none"],
            ["opencode/big-pickle", "opencode/big-pickle", ""],
        ])

    def test_a_failed_listing_gives_the_table_the_same_answer(self):
        self.assertEqual(self.models(), [
            ["mimo/mimo-v2.6-pro", "MiMo V2.6 Pro", "none"],
            ["mimo/mimo-v2.6-flash", "MiMo V2.6 Flash", "none"],
        ])

    def test_mimo_takes_the_effort_none_alone(self):
        with patch.dict(os.environ, self.env), patch.dict(config._CATALOGS, clear=True):
            os.environ.pop(config.ADAPTER_DIR_ENV, None)
            self.assertEqual(config.efforts("opencode", "mimo/mimo-v2.6-pro"), ["none"])

    # --- config ------------------------------------------------------------------
    def test_config_offers_mimo_last(self):
        with open(REPO / "config.default.toml", "rb") as fh:
            cfg = tomllib.load(fh)
        self.assertEqual(config.offered(cfg)[-1], "mimo")
        self.assertEqual(cfg["models"]["mimo"],
                         {"harness": "opencode", "model": "mimo/mimo-v2.6-pro",
                          "effort": "none", "provider": "mimo"})
        self.assertEqual(cfg["providers"]["mimo"], {})   # its mode is the endpoint's


if __name__ == "__main__":
    unittest.main()
