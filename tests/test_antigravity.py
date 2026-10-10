"""Gemini plugs in as a harness through the Antigravity CLI: the adapter's verbs, its screen
rules, its tokens.

Offline and deterministic: a stub `agy` on PATH answers every call with a canned event stream,
every HOME is a temporary directory, and the panes and streams are the real agy 1.2.9
captures under tests/fixtures/.  Nothing here contacts Google or writes to ~/.gemini -- the one
live proof, a real headless turn through the adapter, is the task's proof command, run by hand
on the host.  Never print or copy a real OAuth token here; the only tokens in this file are
the stub's blanks and dummies.
"""

from contextlib import ExitStack
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import box, config, history, menu, run, usage, watch, worker  # noqa: E402

ADAPTER = str(REPO / "adapters/antigravity.sh")
FIXTURES = REPO / "tests/fixtures"

STUB = """#!/usr/bin/env bash
# canned agy for tests/test_antigravity.py: --version answers, `models` renews the login the
# way agy does -- $STUB_RENEWED, when set, written over the token file of the data directory
# it was given -- and anything else prints $STUB_STDERR on stderr, cats $STUB_EVENTS and exits
# $STUB_RC.  Every argv lands in $STUB_ARGV_LOG, the session bus and API key it was handed in
# $STUB_ENV_LOG and whatever stdin held in $STUB_STDIN_LOG, for the assertions.
[ -n "${STUB_ARGV_LOG:-}" ] && printf '%s\\n' "$*" >>"$STUB_ARGV_LOG"
[ -n "${STUB_ENV_LOG:-}" ] &&
  printf '%s|%s\\n' "${DBUS_SESSION_BUS_ADDRESS-}" "${GEMINI_API_KEY-}" >>"$STUB_ENV_LOG"
data=antigravity-cli; case "${1:-}" in --app_data_dir=*) data=${1#*=}; shift ;; esac
[ "${1:-}" = --version ] && { echo "1.2.9-test"; exit 0; }
[ "${1:-}" = models ] && { [ -z "${STUB_RENEWED:-}" ] ||
  cp -- "$STUB_RENEWED" "$HOME/.gemini/$data/antigravity-oauth-token"; exit 0; }
[ -n "${STUB_STDIN_LOG:-}" ] && cat >"$STUB_STDIN_LOG"
[ -n "${STUB_STDERR:-}" ] && printf '%s\\n' "$STUB_STDERR" >&2
cat -- "$STUB_EVENTS"
exit "${STUB_RC:-0}"
"""

# A fake `curl` for the usage verb: the endpoint a URL names answers from the file of that
# name under $HOME/fake -- its code on the first line, its body after -- and a token other
# than the one in $HOME/fake/live is refused 401, as a lapsed one is.  The header comes down
# stdin (`-H @-`); each URL, User-Agent and request body goes to $HOME/fake/asked, never the
# header.  A `hang` file there is an endpoint that never answers and shrugs off a TERM.
FAKE_CURL = """#!/bin/sh
dir="$HOME/fake"; prev=""; url=""
[ -f "$dir/hang" ] && { trap '' TERM; exec sleep 60; }
for a in "$@"; do
  case "$prev" in
    -H) case "$a" in User-Agent:*) printf '%s\\n' "$a" >>"$dir/asked";; esac;;
    -d) printf '%s\\n' "$a" >>"$dir/asked";;
  esac
  case "$a" in https://*) url=$a; printf '%s\\n' "$a" >>"$dir/asked";; esac
  prev=$a
done
[ "$(cut -d' ' -f3)" = "$(cat "$dir/live")" ] || { printf '{}\\n401'; exit 0; }
answer="$dir/${url##*:}"
printf '%s\\n%s' "$(sed 1d "$answer")" "$(head -1 "$answer")"
"""

# The second turn of a real conversation, trimmed: the step's usage is this turn's one model
# call, while the result's usage counts both turns the conversation has had.
EVENTS_CONTINUED = """\
{"event":"init","conversation_id":"c-two","init":{"model":"gemini-3.8-flash"}}
{"event":"step_update","step_update":{"conversation_id":"c-two","step_index":4,"state":"DONE","step_type":"user_input"}}
{"event":"step_update","step_update":{"conversation_id":"c-two","step_index":6,"state":"DONE","step_type":"agent_response","text_delta":"\\n","usage":{"input_tokens":12197,"output_tokens":1,"thinking_tokens":0,"cache_read_tokens":0,"total_tokens":12198}}}
{"event":"result","result":{"conversation_id":"c-two","status":"SUCCESS","response":"two\\n","num_turns":2,"usage":{"input_tokens":36019,"output_tokens":71,"thinking_tokens":0,"cache_read_tokens":0,"total_tokens":36090}}}
"""


class Antigravity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".ak-test-antigravity-", dir=REPO)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "agy").write_text(STUB)
        (self.bin / "agy").chmod(0o755)
        # the usual login unless a test names another: a worker on a named account carries its
        # name, and the probes run in-process here would hand it to the adapter
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
                    "AGENTKIT_SESSION": "fakesession", "AGENTKIT_ACCOUNT": ""}
        self.argv_log = self.root / "argv.log"
        self.token = self.home / ".gemini/antigravity-cli/antigravity-oauth-token"

    def adapter(self, *args, **kwargs):
        env = dict(self.env)
        env.update(kwargs.pop("env", {}))
        return subprocess.run([ADAPTER, *args], capture_output=True, text=True,
                              env=env, **kwargs)

    def write_token(self, refresh):
        """A token file in agy's shape, with a dummy where the refresh token goes."""
        self.token.parent.mkdir(parents=True, exist_ok=True)
        self.token.write_text(json.dumps(
            {"token": {"access_token": "dummy-access", "token_type": "Bearer",
                       "refresh_token": refresh, "expiry": "2026-09-23T21:04:39+02:00"},
             "auth_method": "consumer", "id_token": "dummy-id"}))

    def turn(self, events, *extra, **env):
        """One `run` through the stub, answering with that event stream."""
        out = self.root / "out"
        prompt = self.root / "prompt.md"
        prompt.write_text("You are the executor.\n\nReply with the word done.")
        stream = self.root / "events.jsonl"
        stream.write_text(events)
        proc = self.adapter("run", "gemini-3.8-flash", "high", str(self.root), str(prompt),
                            str(out), *extra,
                            env={"STUB_EVENTS": str(stream), "STUB_ARGV_LOG": str(self.argv_log),
                                 **env},
                            input="a code nobody pasted\n")
        return proc, out

    def pane(self, kind):
        return (FIXTURES / f"antigravity-{kind}-pane.txt").read_text()

    def decide(self, kind):
        return watch.classify("antigravity", watch.pane_tail(self.pane(kind)), None,
                              None, {}, time.time())

    # --- run ---------------------------------------------------------------
    def test_a_turn_may_make_agy_s_project_store(self):
        # agy 1.3.1 opens a conversation only once it has made ~/.gemini/config/projects, and a
        # turn's box keeps every write but those its manifest declares: in a home that has none
        # yet (a fresh login, the live suite's) it refused "mkdir ~/.gemini/config: read-only
        # file system" and the turn exited 1 having done nothing
        workspace, out = self.root / "workspace", self.root / "out"
        workspace.mkdir()
        out.mkdir()
        make = [sys.executable, "-c", "import os, pathlib; pathlib.Path("
                "os.path.expanduser('~/.gemini/config/projects')).mkdir(parents=True)"]
        paths = config.manifest("antigravity")["worker"]
        with box.command(make, {**os.environ, **self.env}, out, cwd=workspace,
                         state=paths["state"], logins=paths["logins"]) as (cmd, env, spawn):
            spawn.pop("stop", None)
            done = subprocess.run(cmd, env=env, cwd=workspace, capture_output=True, text=True,
                                  timeout=60, **spawn)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.home / ".gemini/config/projects").is_dir())

    def test_run_writes_final_session_and_this_turn_s_tokens(self):
        stdin = self.root / "stdin.log"
        proc, out = self.turn((FIXTURES / "antigravity-events.jsonl").read_text(),
                              STUB_STDIN_LOG=str(stdin))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((out / "final.md").read_text(), "done\n")
        self.assertEqual((out / "session_id").read_text(),
                         "0bd34666-b7d8-46e9-a8ba-f6e916cd0374")
        argv = self.argv_log.read_text()
        for flag in ("--output-format stream-json",
                     "--dangerously-skip-permissions", "--print-timeout 0",
                     "--disable-slash-commands", "--model gemini-3.8-flash", "--effort high"):
            self.assertIn(flag, argv)
        self.assertNotIn("--conversation", argv)
        self.assertNotIn("-p", argv.split())
        # the prompt comes down stdin, and the loop's own stdin never reaches agy
        self.assertEqual(stdin.read_text(), "You are the executor.\n\nReply with the word done.")
        # a model agy runs at no effort, configured `none`, is handed no --effort
        self.argv_log.write_text("")
        prompt = self.root / "prompt.md"
        self.adapter("run", "claude-sonnet-4-6", "none", str(self.root), str(prompt),
                     str(self.root / "none"), env={"STUB_EVENTS": str(prompt),
                                                   "STUB_ARGV_LOG": str(self.argv_log)})
        self.assertIn("--model claude-sonnet-4-6", self.argv_log.read_text())
        self.assertNotIn("--effort", self.argv_log.read_text())
        # the stream as agy wrote it, and its two model calls summed: agy's own total for a
        # first turn, read off the steps and not off the result
        self.assertEqual((out / "events.jsonl").read_text(),
                         (FIXTURES / "antigravity-events.jsonl").read_text())
        self.assertEqual(history.event_tokens(out / "events.jsonl"), 23892)

    def test_run_counts_only_this_turn_of_a_continued_conversation(self):
        proc, out = self.turn(EVENTS_CONTINUED, "c-two")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--conversation c-two", self.argv_log.read_text())
        self.assertEqual((out / "final.md").read_text(), "two\n")
        # the result says 36090 for the whole conversation; this turn was one call of 12198
        self.assertEqual(history.event_tokens(out / "events.jsonl"), 12198)

    def test_run_fails_a_turn_agy_ended_as_error(self):
        # agy exits 1 here itself; the stub exits 0 to show the status alone decides
        proc, out = self.turn((FIXTURES / "antigravity-error-events.jsonl").read_text(),
                              "c-before", STUB_STDERR="error: invalid model selection")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual((out / "final.md").read_text(), "")
        # no id in the stream: the turn still belongs to the conversation it continued
        self.assertEqual((out / "session_id").read_text(), "c-before")
        self.assertIn("invalid model selection", (out / "stderr.log").read_text())
        self.assertIsNone(history.event_tokens(out / "events.jsonl"))
        # and the record declares itself the failure the loop reads its refusal words off
        record = json.loads((out / "events.jsonl").read_text())
        self.assertTrue(run.is_failure(record))
        self.assertEqual(run.failures(json.dumps(record), watch.terminal("antigravity"), handed_in=True),
                         [json.dumps(run.without_output(record))])

    def test_a_killed_turn_keeps_its_conversation(self):
        # killed before agy wrote session_id: the retry continues the id the stream opened with
        out = self.root / "killed"
        out.mkdir()
        (out / "events.jsonl").write_text(
            (FIXTURES / "antigravity-events.jsonl").read_text().splitlines()[0] + "\n")
        self.assertEqual(worker.recovered_session(out), "0bd34666-b7d8-46e9-a8ba-f6e916cd0374")

    # --- interactive ---------------------------------------------------------
    def test_interactive_rulebook_is_byte_identical_to_claude(self):
        proc = self.adapter("interactive", "gemini-3.8-flash", "high")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        words = shlex.split(proc.stdout)
        self.assertEqual(words[:3], ["env", "AGY_CLI_DISABLE_AUTO_UPDATE=1", "agy"])
        self.assertEqual(words[words.index("--agent") + 1], "agentkit")
        # the id agy's own alias resolution makes of the model and the effort
        self.assertEqual(words[words.index("--model") + 1], "gemini-3.8-flash-high")
        self.assertIn("--dangerously-skip-permissions", words)
        agents = Path(words[words.index("--add-dir") + 1])
        self.assertEqual(agents.parent, self.home / ".agentkit/state/antigravity")
        self.assertTrue(agents.name.startswith("rulebook-fakesession."))
        text = (agents / ".agents/agents/agentkit/agent.md").read_text()
        head, sep, body = text[4:].partition("\n---\n")
        self.assertTrue(text.startswith("---\n") and sep)
        # the seat runs commands: agy's agent that names no tools never did (see the adapter)
        self.assertEqual(head.splitlines(), ["name: agentkit",
                                             "description: the agentkit orchestrator seat",
                                             "subagent: false", "tools:", "  - run_command"])
        claude = subprocess.run(
            [str(REPO / "adapters/claude.sh"), "interactive", "opus", "xhigh"],
            capture_output=True, text=True, env=self.env)
        self.assertEqual(claude.returncode, 0, claude.stderr)
        cwords = shlex.split(claude.stdout)
        rulebook = cwords[cwords.index("--append-system-prompt-file") + 1]
        self.assertEqual(body.encode(), Path(rulebook).read_bytes())
        # nothing of the seat's goes into the user's own agy configuration
        self.assertFalse((self.home / ".gemini").exists())

    def test_each_seat_keeps_the_rules_it_was_opened_with(self):
        def add_dir(command):
            words = shlex.split(command)
            return Path(words[words.index("--add-dir") + 1])

        def launch(seat, **env):
            proc = self.adapter("interactive", "gemini-3.8-flash", "high",
                                env={"AGENTKIT_SESSION": seat, **env})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return add_dir(proc.stdout)
        first = launch("acme-one")
        opened = (first / ".agents/agents/agentkit/agent.md").read_text()
        (self.home / ".agentkit/rules.md").write_text("acme's own rule\n")
        second = launch("acme-two")
        self.assertIn("acme's own rule",
                      (second / ".agents/agents/agentkit/agent.md").read_text())
        # the second launch leaves the rules the first seat was opened with as they were
        self.assertEqual((first / ".agents/agents/agentkit/agent.md").read_text(), opened)
        # a seat whose rulebook is gone has its definition go at the next launch, and a
        # relaunch of it that lands between that launch's check and its removal keeps its own
        (self.home / ".agentkit/state/rulebook-acme-one.md").unlink()
        (self.bin / "rm").write_text(
            '#!/bin/sh\n[ -z "$RM_FIRST" ] || RM_FIRST= sh -c "$RM_FIRST"\nexec /bin/rm "$@"\n')
        (self.bin / "rm").chmod(0o755)
        relaunched = self.root / "relaunched"
        launch("acme-two", RM_FIRST=(f"AGENTKIT_SESSION=acme-one {shlex.quote(ADAPTER)} "
                                     f"interactive gemini-3.8-flash high >{relaunched}"))
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue((add_dir(relaunched.read_text())
                         / ".agents/agents/agentkit/agent.md").exists())

    def test_interactive_resumes_and_refuses_a_launcher_id(self):
        proc = self.adapter("interactive", "gemini-3.1-pro-high", "high", "c-123")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--conversation c-123", proc.stdout)
        self.assertIn("--model gemini-3.1-pro-high ", proc.stdout)   # already a full id
        # a model agy runs at no effort, configured `none`, is its own full id
        proc = self.adapter("interactive", "claude-sonnet-4-6", "none")
        self.assertIn("--model claude-sonnet-4-6 ", proc.stdout)
        proc = self.adapter("interactive", "gemini-3.8-flash", "high", "launched-id", "new")
        self.assertEqual(proc.returncode, 3)

    # --- auth, usage, install, login, hooks ----------------------------------
    def test_auth_reports_login_presence_and_absence(self):
        proc = self.adapter("auth")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(proc.stderr.splitlines()), 1)
        self.write_token("dummy-refresh")
        for args in (("auth",), ("auth", "seat")):
            proc = self.adapter(*args)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len(proc.stdout.splitlines()), 1)
            self.assertNotIn("dummy", proc.stdout)   # never a word of the token itself
        self.write_token(" ")
        self.assertEqual(self.adapter("auth").returncode, 1)
        self.assertEqual(self.adapter("auth", env={"GEMINI_API_KEY": "k"}).returncode, 0)
        # jq lives in /bin and /usr/bin. A bash on this PATH, and nothing else, is what lets
        # the adapter start without finding jq: the question has no answer, not a `no`.
        (self.bin / "bash").symlink_to(shutil.which("bash"))
        self.assertEqual(self.adapter("auth", env={"PATH": str(self.bin)}).returncode, 2)

    def fake_endpoint(self, summary, live):
        """agy's two quota calls answered offline: its project, then that summary body."""
        self.fake = self.home / "fake"
        self.fake.mkdir(exist_ok=True)
        (self.bin / "curl").write_text(FAKE_CURL)
        (self.bin / "curl").chmod(0o755)
        (self.fake / "loadCodeAssist").write_text(
            '200\n{"currentTier":{"id":"free-tier"},"cloudaicompanionProject":"fixture-project"}\n')
        (self.fake / "retrieveUserQuotaSummary").write_text(f"200\n{summary}")
        (self.fake / "live").write_text(f"{live}\n")
        self.write_token("dummy-refresh")

    def test_usage_reads_the_gemini_window_agy_s_usage_panel_draws(self):
        self.fake_endpoint((FIXTURES / "antigravity-quota-summary.json").read_text(),
                           live="renewed-access")
        # The access token has lapsed and agy renews nothing: a refusal nothing lifted is a
        # failed probe, never a reading.
        usage = json.loads(self.adapter("usage").stdout)
        self.assertEqual(usage["meters"], [])
        self.assertIn("HTTP 401", usage["error"])
        # Once `agy models` renews it, as agy renews its own, the endpoint answers: the Gemini
        # group's window, never the Claude-and-GPT group's, in the shape every adapter prints.
        renewed = self.root / "renewed"
        renewed.write_text(self.token.read_text().replace("dummy-access", "renewed-access"))
        proc = self.adapter("usage", env={"STUB_RENEWED": str(renewed),
                                          "STUB_ARGV_LOG": str(self.argv_log)})
        usage = json.loads(proc.stdout)
        reset = datetime(2026, 9, 30, 11, 48, 46, tzinfo=timezone.utc).timestamp()
        used = usage["meters"][0].pop("used")
        self.assertAlmostEqual(used, 8.2564)   # 1 - 0.917436, unrounded
        self.assertEqual(usage, {"provider": "google", "error": None, "meters": [
            {"name": "gemini-weekly", "resets_at": reset, "window_secs": 604800}]})
        # the share left agy's own panel drew off that same answer
        panel = (FIXTURES / "antigravity-usage-pane.txt").read_text()
        left = float(re.search(r"GEMINI MODELS.*?([\d.]+)%", panel, re.S).group(1))
        self.assertAlmostEqual(100 - used, left, delta=0.005)
        # asked as agy asks, of the project it was given, and nothing but a renewal ran
        asked = (self.fake / "asked").read_text()
        self.assertIn("User-Agent: antigravity/1.2.9-test", asked)
        self.assertIn('{"project":"fixture-project"}', asked)
        self.assertEqual(self.argv_log.read_text().splitlines(), ["--version", "models"])
        # and no token is printed or left behind
        self.assertNotRegex(proc.stdout + proc.stderr + asked, r"\w-access")
        self.assertFalse((self.home / ".agentkit").exists())   # nor written to any file

    def test_usage_answers_inside_its_deadline_whatever_hangs(self):
        # An endpoint that never answers, and a call that ignores TERM: the probe still says
        # so inside its ten seconds, in the words that keep the reading it could not replace --
        # a spent window stays spent -- and never as a logout.
        self.fake_endpoint("", live="dummy-access")
        (self.fake / "hang").touch()
        began = time.monotonic()
        answer = json.loads(self.adapter("usage", timeout=30).stdout)
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual(answer["meters"], [])
        self.assertIn("timed out", answer["error"])
        self.assertEqual(usage.probe_refused(answer["error"]), "unavailable")

    def test_usage_without_a_login_is_a_failed_probe(self):
        # an API key alone is no login here: it has no quota windows to read
        for env in ({}, {"GEMINI_API_KEY": "k"}):
            proc = self.adapter("usage", env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            usage = json.loads(proc.stdout)
            self.assertEqual((usage["provider"], usage["meters"]), ("google", []))
            self.assertIn("no login", usage["error"])
            self.assertNotIn("none", usage)

    def test_a_spent_gemini_window_keeps_gemini_out_of_the_pick(self):
        with open(REPO / "config.default.toml", "rb") as fh:
            cfg = tomllib.load(fh)
        # the clock held a week before the fixture's reset, whatever day this runs on
        now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc).timestamp()
        astra = {"provider": "openai", "meters": [
            {"name": "weekly", "used": 90, "window_secs": 604800, "resets_at": now + 302400}]}
        self.fake_endpoint("", live="dummy-access")
        # Gemini's own window spent parks it; a sliver of it left only ranks it last, and the
        # Claude-and-GPT group spent does not touch it, since no gemini turn draws on it
        for group, left, picked in ((0, 0, ["astra"]), (0, 0.0004, ["astra", "gemini"]),
                                    (1, 0, ["gemini", "astra"])):
            summary = json.loads((FIXTURES / "antigravity-quota-summary.json").read_text())
            summary["groups"][group]["buckets"][0]["remainingFraction"] = left
            (self.fake / "retrieveUserQuotaSummary").write_text(f"200\n{json.dumps(summary)}")
            with self.subTest(group=group, left=left), patch.dict(os.environ, self.env), \
                    patch.object(config, "STATE", self.root / "state"), \
                    patch.object(usage.time, "time", return_value=now):
                providers = {"google": usage._probe(cfg, "google", now), "openai": astra}
                usage._gate_flags({"google": providers["google"]}, now, cfg)
                self.assertIsNone(providers["google"]["error"])
                self.assertEqual(usage.model_exhausted(cfg, "gemini", providers)[0],
                                 "gemini" not in picked)
                order = usage.pick_order(cfg, providers, ["astra", "gemini"],
                                         orchestrator="opus", quiet=True)
                self.assertEqual(order, picked)

    def test_install_login_hooks_verbs(self):
        proc = self.adapter("install")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("already installed (1.2.9-test)", proc.stdout)
        proc = self.adapter("login", stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("run `agy` in a terminal", proc.stderr)
        self.write_token("dummy-refresh")
        proc = self.adapter("login", stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("already logged in", proc.stdout)
        proc = self.adapter("hooks")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("no hooks installed", proc.stdout)
        self.assertEqual([p.name for p in (self.home / ".gemini").rglob("*")
                          if p.is_file()], ["antigravity-oauth-token"])

    # --- accounts ------------------------------------------------------------
    def test_a_named_account_uses_its_own_login_and_the_usual_conversations(self):
        # The usual login is here, beside an API key and a keyring's session bus: none of it
        # may answer for `second`, whose login lives in a data directory of its own.
        self.fake_endpoint((FIXTURES / "antigravity-quota-summary.json").read_text(),
                           live="second-access")
        usual = self.token.read_text()
        env_log = self.root / "env.log"
        named = {"AGENTKIT_ACCOUNT": "second", "GEMINI_API_KEY": "usual-key",
                 "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/usual-bus",
                 "STUB_ARGV_LOG": str(self.argv_log), "STUB_ENV_LOG": str(env_log)}
        own = self.home / ".gemini/antigravity-cli-second/antigravity-oauth-token"
        signin = "DBUS_SESSION_BUS_ADDRESS=disabled: agy --app_data_dir=antigravity-cli-second"
        proc = self.adapter("auth", env=named)
        self.assertEqual((proc.returncode, proc.stderr.splitlines()),
                         (1, [f"agy: no {own}; run `{signin}` and sign in"]))
        proc = self.adapter("login", env=named, stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(f"run `{signin}` in a terminal", proc.stderr)
        self.assertIn(f"no login in {own}", json.loads(self.adapter("usage", env=named).stdout)["error"])
        # signed in to its own home, that login is the one every verb uses
        own.write_text(usual.replace("dummy-access", "second-access"))
        self.assertEqual(self.adapter("auth", env=named).returncode, 0)
        meters = json.loads(self.adapter("usage", env=named).stdout)
        self.assertEqual((meters["error"], len(meters["meters"])), (None, 1))
        proc, out = self.turn(EVENTS_CONTINUED, "c-two", **named)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        words = shlex.split(self.adapter("interactive", "gemini-3.8-flash", "high", "c-two",
                                         env=named).stdout)
        self.assertEqual(words[:11], ["env", "-u", "GEMINI_API_KEY", "-u", "GOOGLE_API_KEY",
                                      "-u", "AGY_ADC_AUTH", "DBUS_SESSION_BUS_ADDRESS=disabled:",
                                      "AGY_CLI_DISABLE_AUTO_UPDATE=1", "agy",
                                      "--app_data_dir=antigravity-cli-second"])
        self.assertEqual(words[words.index("--conversation") + 1], "c-two")
        # `--version` reads no login; the turn is agy on that login's own directory
        calls = self.argv_log.read_text()
        self.assertTrue(calls.startswith(
            "--version\n--app_data_dir=antigravity-cli-second --output-format "), calls)
        self.assertIn(" --conversation c-two\n", calls)
        self.assertEqual(env_log.read_text().splitlines(), ["disabled:|"] * 2)
        # A conversation begun on either account is in the store both read, the usual one's.
        for store in ("conversations", "brain"):
            self.assertEqual((own.parent / store).resolve(),
                             (self.token.parent / store).resolve())
        # and of the usual login nothing was read or changed
        self.assertEqual(self.token.read_text(), usual)
        self.assertEqual(sorted(p.name for p in self.token.parent.iterdir()),
                         ["antigravity-oauth-token", "brain", "conversations"])

    def test_the_usual_login_stays_today_s_beside_a_named_one(self):
        # `default` is the empty name: only the usual login answers, never `second`'s
        self.write_token("dummy-refresh")
        own = self.home / ".gemini/antigravity-cli-second/antigravity-oauth-token"
        own.parent.mkdir(parents=True)
        self.token.rename(own)
        env_log = self.root / "env.log"
        usual = {"AGENTKIT_ACCOUNT": "", "GEMINI_API_KEY": "", "STUB_ENV_LOG": str(env_log),
                 "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/usual-bus"}
        self.assertEqual(self.adapter("auth", env=usual).returncode, 1)
        self.write_token("dummy-refresh")
        self.assertEqual(self.adapter("auth", env=usual).returncode, 0)
        proc, out = self.turn(EVENTS_CONTINUED, "c-two", **usual)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("--app_data_dir", self.argv_log.read_text())
        self.assertEqual(env_log.read_text().splitlines(), ["unix:path=/run/usual-bus|"])
        words = shlex.split(self.adapter("interactive", "gemini-3.8-flash", "high",
                                         env=usual).stdout)
        self.assertEqual(words[:3], ["env", "AGY_CLI_DISABLE_AUTO_UPDATE=1", "agy"])
        self.assertNotIn("--app_data_dir", " ".join(words))
        self.assertEqual([p.name for p in self.token.parent.iterdir()], ["antigravity-oauth-token"])
        self.assertEqual([p.name for p in own.parent.iterdir()], ["antigravity-oauth-token"])

    # --- screen --------------------------------------------------------------
    def test_screen_rules_read_the_captures(self):
        for kind, state, rule in (("prompt", "at_prompt", "prompt.composer"),
                                  ("working", "working", "working.cancel"),
                                  ("dialog", "asking", "asking.trust"),
                                  ("signin", "asking", "asking.signin"),
                                  ("stall", "at_prompt", "prompt.composer"),
                                  # a typed line never sent, and the chooser a `/` opens,
                                  # which says `esc to cancel` too and is no turn in flight
                                  ("draft", "draft", "draft.typed"),
                                  ("chooser", "draft", "draft.chooser")):
            found = self.decide(kind)
            self.assertEqual((found["state"], found["rule"], found["authority"]),
                             (state, rule, "screen"), kind)

    def test_the_end_of_turn_nudge_never_types_into_a_draft(self):
        # The last look saw the seat at its prompt, long enough ago for the rule to act; what
        # is on the screen now decides.  At the prompt the nudge is typed; over a line the
        # owner has typed and not sent, or the chooser a `/` opened, nothing is.
        now = time.time()
        live = {"state": "at_prompt", "stop_said_at": now - 3600, "turn_began": now - 7200}
        # the plan the nudge is judged against lives in ak's state: every path of it sandboxed
        sandbox = ExitStack()
        self.addCleanup(sandbox.close)
        sandbox.enter_context(patch.object(config, "HOME", self.root))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            sandbox.enter_context(patch.object(config, name, self.root / "ak" / name.lower()))
        config.ensure_dirs()
        config.plan_path("seat").write_text("- [ ] the parser parses · check: `false` · acme · written 2026-10-09 12:00\n")    # the seat owes work: the nudge is due
        for kind, typed in (("prompt", 1), ("draft", 0), ("chooser", 0)):
            pane = self.pane(kind)
            with self.subTest(kind=kind), \
                    patch.object(watch, "seat_read", return_value=dict(live)), \
                    patch.object(watch, "hook_facts", return_value={}), \
                    patch.object(watch, "pane_text", return_value=pane), \
                    patch.object(watch, "seat_write"), \
                    patch.object(watch, "type_into", return_value=True) as type_into:
                watch.stop_nudge({"name": "seat"}, "antigravity", pane, None, [], False,
                                 lambda line: None)
                self.assertEqual(type_into.call_count, typed)

    def test_stall_and_auth_words_are_agy_s_own(self):
        mark = watch.stalled_on("antigravity", watch.pane_tail(self.pane("stall")),
                                "seat", lambda _: None)
        self.assertIn(mark, watch.quotas("antigravity"))   # the quota policy runs first
        self.assertIsNone(watch.stalled_on("antigravity", watch.pane_tail(self.pane("prompt")),
                                           "seat", lambda _: None))
        # A 503 whose error id and token count happen to hold 429 is transient, on the screen
        # and headless alike: a status number is only ever read in agy's `(code N)` framing.
        unavailable = "UNAVAILABLE (code 503): The service is currently unavailable."
        pane = self.pane("stall").replace("You have exhausted your quota on this model.",
                                          unavailable).replace("4b2dfd88", "4b2d4290")
        mark = watch.stalled_on("antigravity", watch.pane_tail(pane), "seat", lambda _: None)
        self.assertEqual(mark, "Error ID: ")
        self.assertNotIn(mark, watch.quotas("antigravity"))
        out = self.root / "refused"
        out.mkdir()
        (out / "stderr.log").write_text(f"error: {unavailable}\n")
        (out / "events.jsonl").write_text(json.dumps({"event": "result", "result": {
            "conversation_id": "c-4290-429", "status": "ERROR", "error": unavailable,
            "usage": {"input_tokens": 14290, "total_tokens": 14290}}}) + "\n")
        said = run.harness_said(out, "", "antigravity")
        self.assertEqual(next(word for word in watch.refusals("antigravity")
                              if word.lower() in said.lower()), "UNAVAILABLE")
        self.assertIsNone(run.ran_dry(1, said, "antigravity"))
        # while agy's own words for a spent quota still hand the round over
        self.assertEqual(run.ran_dry(1, "RESOURCE_EXHAUSTED (code 429): quota", "antigravity"),
                         "RESOURCE_EXHAUSTED")
        # a spent Starter quota too, on the screen and headless (agy 1.3.1)
        spent = ("Individual quota reached. Please upgrade your subscription to increase your "
                 "limits. Resets in 51m38s.")
        pane = self.pane("stall").replace("You have exhausted your quota on this model.", spent)
        mark = watch.stalled_on("antigravity", watch.pane_tail(pane), "seat", lambda _: None)
        self.assertIn(mark, watch.quotas("antigravity"))
        self.assertEqual(run.ran_dry(1, f"error: {spent}", "antigravity"), "quota reached")
        # signed out, a headless turn says so on stderr at once and then waits for a code
        out = self.root / "signed-out"
        out.mkdir()
        (out / "stderr.log").write_text(
            "Authentication required. Please visit the URL to log in:\n"
            "  https://accounts.google.com/o/oauth2/auth?client_id=dummy\n\n"
            "Waiting for authentication (timeout 60s)...\n")
        self.assertEqual(worker.auth_scanner("antigravity")(out),
                         "Authentication required. Please visit the URL to log in:")

    # --- history and config -----------------------------------------------------
    def test_history_counts_antigravity_tokens(self):
        # The first attempt was killed before its result event and before the adapter came
        # back: the two calls it finished still count.  Its retry continued the conversation
        # and counts its own call, never the result's total of every turn so far -- so the
        # role's tokens are the conversation's own 36090, each call counted once.
        out = self.root / "executor"
        out.mkdir()
        killed = (FIXTURES / "antigravity-events.jsonl").read_text().splitlines()[:-1]
        (out / "events.jsonl").write_text("\n".join(killed) + "\n")
        self.assertEqual(history.event_tokens(out / "events.jsonl"), 23892)
        retry = self.root / "executor-retry1"
        retry.mkdir()
        (retry / "events.jsonl").write_text(EVENTS_CONTINUED)
        self.assertEqual(history.event_tokens(retry / "events.jsonl"), 12198)
        with patch.object(config, "HOME", self.home):
            history.start_run("r1")
            run.history_role_tokens("r1", "executor", out)
            row = history.get("r1")
        self.assertEqual(row["executor_tokens"], 36090)

    def test_config_offers_gemini_as_both_roles_and_names_it(self):
        with open(REPO / "config.default.toml", "rb") as fh:
            cfg = tomllib.load(fh)
        self.assertEqual(cfg["models"]["gemini"],
                         {"harness": "antigravity", "model": "gemini-3.8-flash",
                          "effort": "high", "provider": "google"})
        self.assertEqual(cfg["providers"]["google"], {"mode": "subscription"})
        self.assertIn("gemini", config.offered(cfg))
        self.assertNotIn("gemini", [cfg["defaults"]["orchestrator"], *cfg["defaults"]["workers"]])
        with patch.object(config, "STATE", self.root / "state"):
            rows = menu.usage_lines(cfg, 100)
        self.assertTrue(any(row.startswith("  Gemini ") for row in rows), rows)


if __name__ == "__main__":
    unittest.main()
