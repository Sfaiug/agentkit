"""A worker turn's failure counts only in whole words the harness itself said.

A `402`, `429` or `529` inside a longer number -- a request id, a byte count -- is no refusal,
and a quota word in the model's own answer parks nothing and waits for nothing.  The words the loop
used to keep itself now live in the harness package and each adapter manifest's `[stall]`, and
still hand a turn over or wait it out as before.  Fake adapters answer from a plan file, the
manifests are the repository's own, and HOME is temporary: no model, meter or real process is
reached.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, orch, run, usage, watch  # noqa: E402
from fixtures.clock import Clock
from fixtures.hand_in import scripted, stateful

# Every harness's adapter: `auth` answers yes, and `run` plays the next row of plan.json, the
# last row again once it is the only one left, ending by the row's signal where it names one.
ADAPTER = '''import json, os, pathlib, sys
if sys.argv[1] == "auth":
    print("fake login")
    sys.exit(0)
if sys.argv[1] != "run":
    sys.exit(2)
plan = pathlib.Path(__file__).with_name("plan.json")
rows = json.loads(plan.read_text())
row = rows.pop(0) if len(rows) > 1 else rows[0]
plan.write_text(json.dumps(rows))
out = pathlib.Path(sys.argv[6])
for name in ("final.md", "stderr.log", "events.jsonl"):
    (out / name).write_text(row.get(name, ""))
(out / "session_id").write_text("s1")
if row.get("signal"):
    os.kill(os.getpid(), row["signal"])
sys.exit(row.get("code", 0))
'''
DONE = {"code": 0, "final.md": "## Summary\nDone.\n"}
BILLING = ("run ended with Failed: API error 402 [request_id=req_acme]: "
           "Billing verification failed. Please check your payment method. (billing_error)")


def stall(harness):
    """The `[stall]` table of that harness's manifest, as the repository ships it."""
    return tomllib.loads((REPO / f"adapters/{harness}.toml").read_text())["stall"]


class QuotaWordsBounded(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-quota-words-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, root / key.lower()))
        self.adapters = root / "adapters"
        self.adapters.mkdir()
        for manifest in (REPO / "adapters").glob("*.toml"):
            script = self.adapters / f"{manifest.stem}.sh"
            script.write_text(f"#!{sys.executable}\n{ADAPTER}")
            script.chmod(0o755)
            stateful(script, self.adapters)
        env = {k: v for k, v in os.environ.items()
               if k not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR",
                            "AGENTKIT_RUN_DIR", "AGENTKIT_SESSION", "AGENTKIT_ACCOUNT")}
        env.update(HOME=str(root), AGENTKIT_ADAPTER_DIR=str(self.adapters), AK_RUN_DEPTH="0",
                   AK_MAX_RUNS="0", AGENTKIT_DISCORD_WEBHOOK="off", PYTHONDONTWRITEBYTECODE="1")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        self.cfg = config.load()
        self.work = root / "workspace"
        self.work.mkdir()
        # the fake usage layer: which account a turn runs on, and what gets parked or spent
        self.account, self.marked, self.lines = None, [], []
        self.stack.enter_context(patch.object(
            usage, "account",
            side_effect=lambda cfg, provider, **_kw: (self.account, False) if self.account
            else (None, None)))
        self.stack.enter_context(patch.object(
            usage, "mark_exhausted", side_effect=lambda *a, **k: self.marked.append(a)))
        self.stack.enter_context(patch.object(usage, "replenish", return_value=(False, 0.0)))
        # a wait nobody expects fails at once, rather than replaying the same turn for ever
        self.sleep = MagicMock(side_effect=AssertionError("waited"))
        self.stack.enter_context(patch.object(run, "time", Clock(self.sleep)))

    def turn(self, model, *rows):
        (self.adapters / "plan.json").write_text(json.dumps(list(rows)))
        return run.call_retrying(self.cfg, model, "Do the task.", self.work,
                                 self.root / "run" / "round-1" / "executor", "executor", None,
                                 self.lines.append, limit=120)

    def test_billing_refusal_parks_each_harness_s_account_and_hands_over_the_round(self):
        # Only execute needs closings; the answer checks must work without a hand-in.
        for adapter in self.adapters.glob("*.sh"):
            adapter.write_text(f"#!{sys.executable}\n{scripted(ADAPTER)}")
        models = {entry["harness"]: name for name, entry in self.cfg["models"].items()}
        self.account = "second"
        for adapter in sorted(self.adapters.glob("*.sh")):
            name, model = adapter.stem, models[adapter.stem]
            with self.subTest(harness=name):
                self.marked.clear()
                self.sleep.reset_mock()
                provider = config.model(self.cfg, model)["provider"]
                other = "astra" if provider == "anthropic" else "opus"
                run_dir = config.RUNS / name
                state = {"executor": model, "reviewer": other, "workers": [model, other],
                         "reviewers": [other], "round_summaries": []}
                lp = SimpleNamespace(cfg=self.cfg, state=state, run_dir=run_dir, wt=self.work,
                                     executor=model, reviewer=other, exec_sid=None, rnd=1,
                                     scratch=True, turn_limit=120, log=self.lines.append,
                                     save=lambda: None, role=lambda role: role,
                                     dir=lambda part: run_dir / "round-1" / part)
                (self.adapters / "plan.json").write_text(json.dumps([
                    {"code": 1, "final.md": BILLING}, DONE]))
                with patch.object(run, "collect_usage", return_value={}):
                    self.assertEqual(run.execute(lp, "executor", "Do the task.", "executor"),
                                     DONE["final.md"])
                self.assertEqual(harness.load(name).failure(BILLING)[0], harness.SPENT)
                self.assertEqual(lp.executor, other)
                self.assertEqual(state["executor_history"][0]["to"], other)
                self.assertIn((self.cfg, provider, None, "second"), self.marked)
                prompt = run_dir / "round-1" / f"executor-{other}" / "prompt.md"
                self.assertIn("Another model started this round", prompt.read_text())
                self.sleep.assert_not_called()

    def test_a_402_inside_a_longer_number_parks_nothing_on_any_harness(self):
        models = {entry["harness"]: name for name, entry in self.cfg["models"].items()}
        said = "Stopped: request req_14020 wrote 14020 bytes in 1.402s."
        for adapter in sorted(self.adapters.glob("*.sh")):
            with self.subTest(harness=adapter.stem):
                code, text, session, dead = self.turn(
                    models[adapter.stem],
                    {"code": 1, "final.md": said, "stderr.log": "exit after 14020ms\n"})
                self.assertEqual((code, text, session, dead), (1, said, "s1", False))
                self.assertEqual(self.marked, [])
                self.sleep.assert_not_called()

    def test_billing_words_also_park_a_harness_without_a_manifest(self):
        for word in ("402", "billing_error", "payment required"):
            with self.subTest(word=word):
                self.assertEqual(harness.load("acme").failure(word), (harness.SPENT, word))

    def test_billing_refusal_skips_smoke_check_three_and_parks_its_snapshot(self):
        out = self.root / "refused"
        out.mkdir()
        (out / "final.md").write_text(BILLING)
        snapshot = self.root / "usage-real.json"
        snapshot.write_text('{"providers": {}}')
        # The helper can read a refused call without starting the suite's real models.
        source = (REPO / "tests/smoke.sh").read_text()
        helper = "skip_refused() {" + source.split("skip_refused() {", 1)[1].split("\n}\n", 1)[0]
        script = ('skip_spent_checks() { printf "%s %s\\n" "$@"; }\n'
                  + helper + '\n}\nskip_refused 3a/3b spark 1 "$WORK/refused"\n')
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                              env={**os.environ, "REPO": str(REPO), "WORK": str(self.root)},
                              timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("3a/3b required model spark was refused: " + BILLING, proc.stdout)
        self.assertGreater(json.loads(snapshot.read_text())["providers"]["meta"][
            "exhausted_until"], time.time())

    def test_a_429_or_529_inside_a_longer_number_neither_parks_nor_waits(self):
        # Every one of these harnesses lists `429` as a spent window and `529` as a refusal.
        said = "Stopped: request req_84290 wrote 15290 bytes in 1.529s."
        for model, harness in (("opus", "claude"), ("astra", "codex"), ("spark", "muse")):
            with self.subTest(model=model):
                self.assertIn("429", stall(harness)["quotas"])
                self.assertIn("529", stall(harness)["refusals"])
                code, text, session, dead = self.turn(
                    model, {"code": 1, "final.md": said, "stderr.log": "exit after 45290ms\n"})
                self.assertEqual((code, text, session, dead), (1, said, "s1", False))
                self.assertEqual(self.marked, [])
                self.sleep.assert_not_called()

    def test_a_quota_word_in_the_model_s_answer_parks_nothing(self):
        self.account = "second"
        answer = ("## Summary\nTaught the retry to read `usage limit reached`, "
                  "`429 Too Many Requests`, `402`, `billing_error` and `payment required` "
                  "as a spent window.\n")
        code, text, _, _ = self.turn("opus", {"code": 1, "final.md": answer})
        self.assertEqual((code, text), (1, answer))
        self.assertEqual(self.marked, [])
        self.assertFalse([line for line in self.lines if "ran dry" in line], self.lines)
        # nor does an outage the answer talks about wait for anything
        answer = ("## Summary\nThe client now retries `API Error: 529 Overloaded` and "
                  "`503 Service unavailable` itself.\n")
        code, text, _, _ = self.turn("astra", {"code": 1, "final.md": answer})
        self.assertEqual((code, text), (1, answer))
        self.sleep.assert_not_called()

    def test_a_word_moved_out_of_the_loop_still_hands_over_or_waits(self):
        # a harness that never ran the turn hands it over at once, in the words no harness owns
        line = "The model gpt-nonexistent was not found. Try a different model."
        self.assertIn("model … not found", harness.STALL["faults"])
        with self.assertRaises(run.CannotRun) as broken:
            self.turn("astra", {"code": 1, "stderr.log": f"{line}\n"})
        self.assertIn(line, str(broken.exception))
        self.sleep.assert_not_called()
        # ... unless the provider was down beside it, which is waited out on the same session
        self.assertIn("Can't reach the API server", harness.STALL["outages"])
        self.sleep.side_effect = None
        code, text, session, _ = self.turn(
            "opus", {"code": 1, "stderr.log": "error: unknown option '--effort'\n"
                                              "Can't reach the API server\n"}, DONE)
        self.assertEqual((code, session), (0, "s1"))
        self.assertIn("Done.", text)
        self.assertEqual(self.sleep.call_args_list, [((60,),)])
        # and an outage the harness put where the answer belongs is waited out as before
        self.assertIn("HTTP~5##", harness.STALL["outages"])
        self.sleep.reset_mock()
        code, text, _, _ = self.turn("astra", {"code": 1, "final.md": "HTTP 520 upstream"}, DONE)
        self.assertEqual(code, 0)
        self.assertEqual(self.sleep.call_args_list, [((60,),)])
        self.assertEqual(self.marked, [])

    def test_what_the_loop_read_before_it_reads_the_same(self):
        # a model the harness does not know, or a refused login, hands over whatever the model
        # is called -- and a status number with no HTTP beside it never waits one out
        for model, stderr in (("opus", "Error: model claude-acme does not exist"),
                              ("astra", "Error: model gpt-acme not found"),
                              ("astra", "Error: model gpt-acme is not supported"),
                              ("astra", "Error: modelnot_found"), ("astra", "model_notfound"),
                              ("opus", "Error: authentication_required"),
                              ("opus", "Please /login"), ("opus", "Please run /log in"),
                              ("astra", "invalid-api_key"), ("astra", "invalid x-api_key"),
                              ("opus", "error: unknown option '--effort'\nrequest count: 500"),
                              ("astra", "error: unknown option '--effort'\nrequest count: 529")):
            with self.subTest(stderr=stderr), self.assertRaises(run.CannotRun):
                self.turn(model, {"code": 1, "stderr.log": stderr})
        self.sleep.assert_not_called()
        # a warning that something else was not found is no fault, and an outage in any of its
        # spellings outranks one that is: the empty turn is waited out
        self.sleep.side_effect = None
        for stderr in ("warning: cached response was not found\nstream disconnected",
                       "warning: cache directory does not exist\nstream disconnected",
                       'warning: optional tool is not installed\n{"status":503}',
                       'warning: optional tool is not installed\n{"status": 503}',
                       "warning: optional tool is not installed\nHTTP: 503",
                       "warning: optional tool is not installed\nAPI Error:503"):
            with self.subTest(stderr=stderr):
                self.sleep.reset_mock()
                code, _, _, _ = self.turn("astra", {"code": 1, "stderr.log": stderr}, DONE)
                self.assertEqual((code, self.sleep.call_args_list), (0, [((60,),)]))
        # a kill by signal takes its own road, whatever the harness said before it
        self.sleep.reset_mock(side_effect=True)
        self.sleep.side_effect = AssertionError("waited")
        with self.assertRaises(run.Killed):
            self.turn("astra", {"signal": 15, "final.md": "API Error: request interrupted"})
        self.sleep.assert_not_called()


class SeatWordsBounded(unittest.TestCase):
    """A seat's pane is read by the same reader: its error line, whole words, never the answer."""

    def setUp(self):
        QuotaWordsBounded.setUp(self)     # the same temporary HOME and fake usage layer
        self.now = 1_800_000_000
        self.stack.enter_context(patch.object(watch.time, "time", lambda: self.now))
        self.seat = {"name": "fix-api"}
        self.stack.enter_context(patch.object(orch, "sessions", lambda: [self.seat]))
        self.harness, self.provider, self.pane = "claude", "anthropic", ""
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              lambda *_: (self.harness, self.provider)))
        self.stack.enter_context(patch.object(watch, "pane_text", lambda _: self.pane))
        self.typed = []
        self.stack.enter_context(patch.object(
            watch, "type_into", side_effect=lambda _, keys, *a, **k: self.typed.append(keys) or True))
        self.stack.enter_context(patch.object(watch.notify, "shaped", return_value=0))
        self.window = self.stack.enter_context(
            patch.object(watch, "window_ends", side_effect=lambda *_: self.now + 7200))

    def tick(self, state, seconds=0, cfg=None):
        self.now += seconds
        watch.health({} if cfg is None else cfg, state, False, self.lines.append)

    def test_a_429_inside_a_longer_number_on_a_seat_s_error_line_is_no_quota(self):
        # Muse and OpenCode both list `429` as a stall signature and as a spent window.
        for harness, error in (("muse", "◆ model failed: request req_84290 reset after 15290 "
                                        "bytes (after 10 provider attempts)"),
                               ("opencode", "Error: request req_84290 failed after 45290ms")):
            with self.subTest(harness=harness):
                self.assertIn("429", stall(harness)["signatures"])
                self.assertIn("429", stall(harness)["quotas"])
                pane = f"Reading the next file\n{error}\n"
                mark = watch.stalled_on(harness, watch.pane_tail(pane), "fix-api", self.lines.append)
                self.assertNotIn(mark, watch.quotas(harness))
                entry = {}
                watch.observe(entry, pane, harness, self.now)
                self.assertEqual(entry["stall_line"], "" if mark is None else error)
        # and a stalled seat whose only 429 is inside a number is typed at, never waited out
        self.harness, self.provider, self.pane = "opencode", "mimo", error
        state = watch.load_state()
        self.tick(state)
        self.tick(state, watch.STALL_WAIT)
        self.assertEqual(self.typed, ["continue"])
        self.window.assert_not_called()
        # nor is a usage probe's 401 read as a rate limit by one, while HTTP's own 429 still is
        self.assertIsNone(usage.probe_refused(
            "unknown: HTTP 401 from api.example/usage after 1.429 s; run acme login"))
        self.assertEqual(usage.probe_refused("unknown: HTTP 429 from api.example/usage"),
                         "rate limited")

    def test_a_quota_word_in_the_answer_above_an_unrelated_error_parks_nothing(self):
        answer = ("Taught the retry to read usage limit reached and 429 Too Many Requests "
                  "as a spent window.")
        for harness, provider, pane in (
                ("claude", "anthropic", f"● {answer}\n⎿ API Error: 500 Internal server error"),
                ("codex", "openai", f"• {answer}\n■ Selected model is at capacity. "
                                    "Please try a different model."),
                # an error line naming no failure of its own reads no answer above it either
                ("opencode", "mimo", "Documented quota exhausted.\nError: connection closed"),
                ("codex", "openai", "Documented quota exhausted.\nGoal stalled"),
                ("antigravity", "google", "Documented quota exhausted.\nError ID: 4b2d-1")):
            with self.subTest(harness=harness, pane=pane):
                self.harness, self.provider, self.pane = harness, provider, pane
                self.typed.clear()
                self.window.reset_mock()
                state = watch.load_state()
                self.tick(state)
                self.tick(state, watch.STALL_WAIT)
                # no window waited on: the error is typed at, as any other
                self.window.assert_not_called()
                self.assertNotIn("status", state["stalls"]["fix-api"])
                self.assertEqual(self.typed, [watch.keystroke(harness, pane)])
                self.assertEqual(self.marked, [])
        # while the same words on the error line the harness drew still wait on the window
        for harness, provider, pane in (
                ("codex", "openai", "■ You've hit your usage limit.\nGoal stalled"),
                ("antigravity", "google", "⚠ You have exhausted your quota on this model.\n"
                                          "Error ID: 4b2d-1")):
            with self.subTest(harness=harness, pane=pane):
                self.harness, self.provider, self.pane, self.typed = harness, provider, pane, []
                self.window.reset_mock()
                state = watch.load_state()
                self.tick(state)
                self.tick(state, watch.STALL_WAIT)
                self.window.assert_called_once()
                self.assertEqual(self.typed, [])
                self.assertTrue(state["stalls"]["fix-api"]["status"].startswith("waiting until "))

    def seat_account(self, harness, model, provider, pane):
        """One pass of the account policy over that seat, which runs on its only login."""
        config.save_session(self.cfg, "fix-api", model, [model], {"cwd": str(self.work)})
        self.harness, self.provider, self.pane = harness, provider, pane
        collected = {provider: {"provider": provider, "meters": [], "resets": 0}}
        with patch.object(usage, "collect", return_value=collected), \
                patch.object(watch, "boot_id", return_value="boot"):
            return watch.seat_account(self.cfg, self.seat, harness, provider, pane, False,
                                      self.lines.append)

    def test_a_bare_rate_limit_is_still_retried_in_place(self):
        for harness, model, provider, pane in (
                ("claude", "opus", "anthropic", "⎿ API Error: 429 rate limit"),
                ("codex", "astra", "openai",
                 "■ exceeded retry limit, last status: 429 Too Many Requests"),
                ("codex", "astra", "openai", "• stream error: rate limit reached")):
            with self.subTest(pane=pane):
                self.typed.clear()
                watch.seat_write("fix-api", usage_refusal=None, usage_wait=None)
                self.assertTrue(self.seat_account(harness, model, provider, pane))
                self.now += watch.STALL_WAIT
                self.assertTrue(self.seat_account(harness, model, provider, pane))
                self.assertEqual(self.typed, [watch.keystroke(harness, pane)])
                self.assertEqual(self.marked, [])
        # a spent window on the same line parks the account it ran on
        watch.seat_write("fix-api", usage_refusal=None, usage_wait=None)
        pane = "⎿ API Error: 429 Usage limit reached"
        self.seat_account("claude", "opus", "anthropic", pane)
        self.now += watch.STALL_WAIT
        self.seat_account("claude", "opus", "anthropic", pane)
        self.assertEqual([call[1] for call in self.marked], ["anthropic"])
        # as does a deadline an older Codex's own `• stream error:` line names
        watch.seat_write("fix-api", usage_refusal=None, usage_wait=None)
        pane = "• stream error: rate limit reached. Try again at " + time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(self.now + 7200))
        self.seat_account("codex", "astra", "openai", pane)
        self.now += watch.STALL_WAIT
        self.seat_account("codex", "astra", "openai", pane)
        self.assertEqual([call[1] for call in self.marked], ["anthropic", "openai"])

    def test_a_spent_window_a_bare_trailer_closes_parks_the_account(self):
        # `Goal stalled` and `Error ID:` name no failure: the error line drawn above them does
        for harness, model, provider, pane in (
                ("codex", "astra", "openai", "■ You've hit your usage limit.\nGoal stalled"),
                ("antigravity", "gemini", "google",
                 "⚠ You have exhausted your quota on this model.\nError ID: 4b2d-1")):
            with self.subTest(harness=harness):
                self.marked.clear()
                watch.seat_write("fix-api", usage_refusal=None, usage_wait=None)
                self.seat_account(harness, model, provider, pane)
                self.now += watch.STALL_WAIT
                self.seat_account(harness, model, provider, pane)
                self.assertEqual([call[1] for call in self.marked], [provider])

    def test_a_bare_trailer_s_refusal_is_dated_and_told_apart_by_its_error_line(self):
        # a deadline the host slept through is retried in place, never parked again
        self.marked.clear()
        watch.seat_write("fix-api", usage_refusal=None, usage_wait=None)
        pane = "■ You've hit your usage limit. Try again at 2027-01-15 07:00Z\nGoal stalled"
        self.seat_account("codex", "astra", "openai", pane)
        self.now += watch.STALL_WAIT
        self.assertTrue(self.seat_account("codex", "astra", "openai", pane))
        self.assertEqual((self.marked, self.typed), ([], ["/goal resume"]))
        # and a later, different error over the same trailer is not that handled refusal
        pane = "■ Selected model is at capacity. Please try a different model.\nGoal stalled"
        self.assertFalse(self.seat_account("codex", "astra", "openai", pane))

    def test_a_quota_word_in_the_model_s_last_answer_parks_nothing(self):
        # As Claude 2.1.286 draws them, captured with attributes: the same `●` begins the
        # model's answer and its own notice, and only the notice's words are in a colour.
        dot = "\x1b[38;5;231m\x1b[49m●\x1b[39m "
        said = "Added handling for Usage limit reached."
        for harness, model, provider, pane in (
                ("claude", "opus", "anthropic", f"{dot}{said}"),
                ("claude", "opus", "anthropic", f"{dot}Done.\n  {said}"),
                # a span it styles in colour, the same answer with no colour at all, and Codex's
                ("claude", "opus", "anthropic",
                 f"{dot}Added handling for \x1b[38;5;153mUsage limit reached\x1b[39m."),
                ("claude", "opus", "anthropic", f"● {said}"),
                ("codex", "astra", "openai", f"• {said}")):
            with self.subTest(pane=pane):
                self.marked.clear()
                self.window.reset_mock()
                watch.seat_write("fix-api", usage_refusal=None, usage_wait=None)
                self.seat_account(harness, model, provider, pane)
                self.now += watch.STALL_WAIT
                self.seat_account(harness, model, provider, pane)
                self.assertEqual([call[1] for call in self.marked], [])
                state = watch.load_state()
                self.tick(state)
                self.tick(state, watch.STALL_WAIT)
                self.window.assert_not_called()
                self.assertNotIn("status", state["stalls"].get("fix-api", {}))
                # Codex's answer behind its `•` is still a stall, typed at as any other
                self.assertEqual("fix-api" in state["stalls"], harness == "codex")
        # while a notice it draws in colour still parks the account it ran on, a colour tmux
        # carries on from the line above included
        for pane in ("\x1b[38;5;220m\x1b[49m●\x1b[39m \x1b[38;5;220mAPI Error: 429 Usage limit reached",
                     "\x1b[38;5;220m● first coloured line\nAPI Error: 429 Usage limit reached\n"
                     "\x1b[39m❯"):
            with self.subTest(pane=pane):
                self.marked.clear()
                watch.seat_write("fix-api", usage_refusal=None, usage_wait=None)
                self.seat_account("claude", "opus", "anthropic", pane)
                self.now += watch.STALL_WAIT
                self.seat_account("claude", "opus", "anthropic", pane)
                self.assertEqual([call[1] for call in self.marked], ["anthropic"])


    def test_a_limit_notice_over_a_status_line_parks_the_account(self):
        # Claude 2.1.286's own bytes, captured on a renamed seat: its two-line weekly-limit
        # notice, the seat's name in the composer's top rule, a user's status line under it.
        pane = "\n".join([
            "  \x1b[38;5;231med-o/result.md. Decide the next step.\x1b[39m",
            "\x1b[38;5;246m\x1b[49m  ⎿ \xa0\x1b[38;5;211m\x1b[48;5;66mYou've hit your weekly limit"
            " · resets Oct 2, 2pm (Europe/Berlin)\x1b[39m",
            "\x1b[49m     \x1b[38;5;246m\x1b[48;5;66m/usage-credits to finish what you’re working on."
            "\x1b[39m",
            "\x1b[38;5;246m\x1b[49m✻\x1b[39m \x1b[38;5;246mChurned for 0s · done 8:57 AM",
            "\x1b[39m",
            "\x1b[38;5;244m" + "─" * 69 + " fix-api ─",
            "\x1b[39m❯",
            "\x1b[38;5;244m" + "─" * 80,
            "\x1b[39m  \x1b[1m\x1b[32muser@host\x1b[0m\x1b[38;5;246m:\x1b[1m\x1b[34m~/code\x1b[0;2m"
            "\x1b[38;5;246m | \x1b[0m\x1b[38;5;246mOpus 5.5\x1b[2m | \x1b[0m\x1b[32mctx ▓░░░░░░░░░ "
            "104.7k/1M (10…",
            "\x1b[39m  \x1b[38;5;211m⏵⏵ bypass permissions on\x1b[38;5;246m (shift+tab to cycle)"
            " · ← for agents",
        ])
        self.assertEqual(watch.stalled_on("claude", pane, "fix-api", self.lines.append),
                         "weekly limit")
        self.assertEqual(watch.composer_draft("claude", pane), "")
        self.seat_account("claude", "opus", "anthropic", pane)
        self.now += watch.STALL_WAIT
        self.seat_account("claude", "opus", "anthropic", pane)
        self.assertEqual([call[1] for call in self.marked], ["anthropic"])


if __name__ == "__main__":
    unittest.main()
