"""A seat's provider error is read from its harness's own record of the conversation.

Claude writes a failed request into the transcript as an `isApiErrorMessage` entry, Codex ends a
failed turn in its rollout with a `task_complete` whose `error` says why; a model's answer is
never such an entry.  Where a seat's harness keeps that record, the tick's stall, account, auth
and health readers classify its text, so an error wrapped over two rows is still seen, and an
answer quoting a quota -- wrapped or not, coloured or not -- is no stall and parks nothing.
Entries have the shapes the harnesses write, under invented ids; HOME is temporary, and no
model, meter, pane or process is reached.
"""

from contextlib import ExitStack
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, usage, watch  # noqa: E402
from agentkit.harness import claude, codex  # noqa: E402

MODELS = {"claude": ("opus", "anthropic"), "codex": ("astra", "openai")}
AT = "2026-10-01T06:00:00.000Z"
# What each kind of error the two harnesses record reads as.  The Codex refusal names its own
# deadline; the Claude one ends in its epoch, which no reader dates.
CASES = (
    ("claude", "rate_limit", 429, "Claude AI usage limit reached|1800003600", "spent"),
    ("claude", "rate_limit", 429,
     'API Error: 429 {"type":"error","error":{"type":"rate_limit_error","message":"This '
     "request would exceed your account's rate limit. Please try again later.\"}}", "limited"),
    ("claude", "authentication_failed", None, "Login expired · Please run /login", "auth"),
    ("claude", "server_error", 529,
     "API Error: 529 Overloaded. This is a server-side issue, usually temporary — try again "
     "in a moment. If it persists, check status.claude.com.", "outage"),
    ("codex", "usage_limit_exceeded", None,
     "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to purchase "
     "more credits or try again at Oct 3rd, 2027 10:32 PM.", "spent"),
    ("codex", {"response_too_many_failed_attempts": {"http_status_code": 429}}, None,
     "exceeded retry limit, last status: 429 Too Many Requests", "limited"),
    ("codex", "other", None,
     "Your access token could not be refreshed because your refresh token has expired. "
     "Please log out and sign in again.", "auth"),
    ("codex", "server_overloaded", None,
     "Selected model is at capacity. Please try a different model.", "outage"),
)
DOT = "\x1b[38;5;231m\x1b[49m●\x1b[39m "
SAID = "Added handling for Usage limit reached."
# Answers quoting a quota, as each harness draws them: the reviewers' probes of
# tests/test_quota_words_bounded.py, the task's own, and rows a wrap could join into one.
ANSWERS = (
    ("claude", f"{DOT}{SAID}"), ("claude", f"{DOT}Done.\n  {SAID}"),
    ("claude", f"{DOT}Added handling for \x1b[38;5;153mUsage limit reached\x1b[39m."),
    ("claude", f"● {SAID}"), ("codex", f"• {SAID}"),
    ("codex", "• Done.\n  Added handling for usage limit reached."),
    ("claude", "● Usage limit reached is now retried."),
    ("claude", f"{DOT}Usage limit reached is now retried."),
    ("claude", "● Fixed it.\n  API Error: 429 Usage\n  limit reached is now retried."),
    ("claude", "\x1b[38;5;210m● API Error: 400 Usage limit reached\x1b[39m\n\n  Request succeeded"),
    ("claude", "  ⎿  API Error: 401 Please run /login\n     Retried successfully"),
    ("codex", "  └ usage limit: 100\n    current usage: 1"),
    ("codex", "• You've hit your usage\n  limit handling is now tested."),
)


def claude_entry(kind, **fields):
    return {"parentUuid": None, "isSidechain": False, "userType": "external",
            "cwd": "/srv/acme", "sessionId": "c0ffee00-0000-4000-8000-000000000001",
            "version": "2.1.286", "gitBranch": "fix-api", "type": kind,
            "uuid": "5e1f0c2a-0000-4000-8000-00000000000a", "timestamp": AT, **fields}


def prompt(text):
    return claude_entry("user", message={"role": "user", "content": text})


def answer(text):
    return claude_entry("assistant", requestId="req_011Acme", message={
        "id": "msg_011Acme", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
        "stop_sequence": None})


def api_error(kind, status, text):
    return claude_entry("assistant", requestId="req_011Acme", error=kind, isApiErrorMessage=True,
                        apiErrorStatus=status, message={
                            "id": "6d1c9a52-0000-4000-8000-00000000000b", "container": None,
                            "model": "<synthetic>", "role": "assistant", "stop_details": None,
                            "stop_reason": "stop_sequence", "stop_sequence": "",
                            "type": "message", "content": [{"type": "text", "text": text}]})


# what Claude writes beside a conversation, after an error as anywhere else
BOOKKEEPING = (claude_entry("system", subtype="turn_duration", durationMs=1840, isMeta=False),
               {"type": "last-prompt", "lastPrompt": "Fix the API", "sessionId": "c0ffee00"})


def codex_event(kind, **payload):
    return {"timestamp": AT, "type": "event_msg", "payload": {"type": kind, **payload}}


def started(turn):
    return codex_event("task_started", turn_id=turn, started_at=1800000000,
                       model_context_window=258400, collaboration_mode_kind="default")


def item(role, text):
    return {"timestamp": AT, "type": "response_item", "payload": {
        "type": "message", "id": "msg_01acme", "role": role,
        "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}}


def completed(turn, last=None, error=None):
    return codex_event("task_complete", turn_id=turn, last_agent_message=last,
                       **({"error": error} if error else {}), started_at=1800000000,
                       completed_at=1800000060, duration_ms=60000)


def failed(harness, kind, status, text):
    """A turn that ended on that error, in its harness's own record."""
    if harness == "claude":
        return [prompt("Fix the API."), api_error(kind, status, text), *BOOKKEEPING]
    return [started("turn-1"), item("user", "Fix the API."),
            completed("turn-1", error={"message": text, "codex_error_info": kind})]


def answered(harness, text):
    """A turn that ended on the model's answer, in its harness's own record."""
    if harness == "claude":
        return [prompt("Fix the API."), answer(text), *BOOKKEEPING]
    return [started("turn-1"), item("user", "Fix the API."), item("assistant", text),
            completed("turn-1", last=text)]


def wrapped(harness, text):
    """That error as a narrow pane draws it: over rows no screen reader joins."""
    rows = textwrap.wrap(text, 28)
    return ("⎿  " if harness == "claude" else "■ ") + "\n   ".join(rows)


class SeatErrorRecord(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-seat-error-record-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, root / key.lower()))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_"))
               and k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
        env.update(HOME=str(root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AGENTKIT_DISCORD_WEBHOOK="off", AGENTKIT_TMUX_SOCKET="agentkit-test",
                   PYTHONDONTWRITEBYTECODE="1")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        self.cfg = config.load()
        self.work = root / "acme"
        self.work.mkdir()
        self.now, self.seats = 1_800_000_000, 0
        self.stack.enter_context(patch.object(watch.time, "time", lambda: self.now))
        self.seat = {"name": "fix-api"}
        self.stack.enter_context(patch.object(orch, "sessions", lambda: [self.seat]))
        # Health also types titles and publishes bars, beyond the mocked stall nudge.
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              lambda *_: (self.harness, self.provider)))
        self.stack.enter_context(patch.object(watch, "pane_text", lambda _: self.pane))
        self.stack.enter_context(patch.object(watch, "boot_id", return_value="boot"))
        self.typed, self.marked, self.lines = [], [], []
        self.stack.enter_context(patch.object(
            watch, "type_into", side_effect=lambda _, keys, *a, **k: self.typed.append(keys) or True))
        self.stack.enter_context(patch.object(
            usage, "mark_exhausted", side_effect=lambda cfg, provider, **kw: self.marked.append(
                (provider, kw.get("until")))))
        self.stack.enter_context(patch.object(watch.notify, "shaped", return_value=0))
        self.auth = self.stack.enter_context(patch.object(watch, "record_auth"))
        self.reset = self.stack.enter_context(patch.object(watch, "spend_reset"))
        self.window = self.stack.enter_context(
            patch.object(watch, "window_ends", side_effect=lambda *_: self.now + 7200))

    def record(self, harness, entries, pane):
        """A new seat of that harness, its record holding those entries and its pane that."""
        self.seats += 1
        name = self.seat["name"] = f"fix-api-{self.seats}"
        thread = f"0d9b6c1e-5a2f-4c7e-9e1a-3f2b8c4d6a{self.seats:02d}"
        model, self.provider = MODELS[harness]
        self.harness, self.pane = harness, pane
        self.typed.clear()
        self.marked.clear()
        for mock in (self.auth, self.reset, self.window):
            mock.reset_mock()
        lines = "".join(json.dumps(entry) + "\n" for entry in entries)
        if harness == "claude":
            config.save_session(self.cfg, name, model, [model], {
                "cwd": str(self.work), "conversation": thread, "id_source": orch.LAUNCHER})
            slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.work))
            path = self.root / ".claude/projects" / slug / f"{thread}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(lines)
            return name
        config.save_session(self.cfg, name, model, [model], {"cwd": str(self.work)})
        path = self.root / f"rollout-{thread}.jsonl"
        path.write_text(json.dumps({"timestamp": AT, "type": "session_meta", "payload": {
            "session_id": thread, "id": thread, "cwd": str(self.work), "originator": "codex_cli_rs",
            "cli_version": "0.153.4"}}) + "\n" + lines)
        receipt = codex.prepare(name, self.work, None)
        codex.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
                                "session_id": thread, "transcript_path": str(path),
                                "cwd": str(self.work)})
        return name

    def account(self, name):
        """Two passes of the account policy over that seat, a stall's wait apart."""
        collected = {self.provider: {"provider": self.provider, "meters": [], "resets": 0}}
        with patch.object(usage, "collect", return_value=collected):
            for _ in range(2):
                watch.seat_account(self.cfg, self.seat, self.harness, self.provider, self.pane,
                                   False, self.lines.append)
                self.now += watch.STALL_WAIT

    def health(self, name):
        """Two passes of the tick's stall reading over that seat, a stall's wait apart."""
        state = watch.load_state()
        for _ in range(2):
            watch.health({}, state, False, self.lines.append)
            self.now += watch.STALL_WAIT
        return state["stalls"].get(name, {})

    def test_each_recorded_error_reads_its_outcome_and_reset(self):
        for harness, kind, status, text, outcome in CASES:
            with self.subTest(harness=harness, kind=kind, outcome=outcome):
                name = self.record(harness, failed(harness, kind, status, text),
                                   wrapped(harness, text))
                # the record's own text, its reset with it, wrapped on the pane or not
                self.assertEqual(watch.recorded_error(harness, name), text)
                word = watch.stalled_on(harness, self.pane, name, self.lines.append)
                signature = watch.auth_expired_on(harness, self.pane, name)
                self.assertEqual(bool(signature), outcome == "auth")
                self.assertEqual(word is None, outcome == "auth")
                self.account(name)
                until = run.try_again_at(text)
                self.assertEqual(self.marked,
                                 [(self.provider, until)] if outcome == "spent" else [])
                if outcome == "spent" and harness == "codex":
                    self.assertEqual(until, datetime(2027, 10, 3, 22, 32).timestamp())
                # a bare rate limit is retried in place
                self.assertEqual(self.typed, ["continue"] if outcome == "limited" else [])
                if outcome in ("spent", "limited"):
                    self.assertIn(word, watch.quotas(harness))
                    continue
                entry = self.health(name)
                if outcome == "auth":
                    # the login verb is asked, and a login is never typed at
                    self.assertTrue(self.auth.call_args.kwargs["fresh"])
                    self.assertEqual((self.typed, entry.get("signature")), ([], None))
                else:
                    # an outage is typed at, and waits on no window and spends no reset
                    self.assertEqual(entry["signature"], word)
                    self.assertEqual(self.typed, [watch.keystroke(harness, self.pane)])
                    self.reset.assert_not_called()
                    self.window.assert_not_called()
        # while a spent window the tick reads waits on it, never typing
        name = self.record("codex", failed("codex", *CASES[4][1:4]), "❯")
        self.assertTrue(self.health(name)["status"].startswith("waiting until "))
        self.assertEqual(self.typed, [])

    def test_a_recorded_error_followed_by_a_newer_prompt_is_no_stall(self):
        for harness, kind, status, text, _ in CASES:
            with self.subTest(harness=harness, kind=kind):
                newer = ([prompt("continue")] if harness == "claude"
                         else [started("turn-2"), item("user", "continue")])
                name = self.record(harness, failed(harness, kind, status, text) + newer,
                                   wrapped(harness, text))
                self.assertEqual(watch.recorded_error(harness, name), "")
                self.assertIsNone(watch.stalled_on(harness, self.pane, name, self.lines.append))
                self.assertIsNone(watch.auth_expired_on(harness, self.pane, name))
                self.account(name)
                self.assertEqual((self.marked, self.typed), ([], []))
                self.assertEqual(self.health(name), {})
                self.assertEqual(self.typed, [])
                self.auth.assert_not_called()

    def test_an_answer_quoting_a_quota_is_no_stall_and_parks_nothing(self):
        for harness, pane in ANSWERS:
            with self.subTest(harness=harness, pane=pane):
                text = " ".join(watch.strip_sgr(pane).split())
                name = self.record(harness, answered(harness, text), pane)
                self.assertEqual(watch.recorded_error(harness, name), "")
                self.assertIsNone(watch.stalled_on(harness, pane, name, self.lines.append))
                self.assertIsNone(watch.auth_expired_on(harness, pane, name))
                self.account(name)
                self.assertEqual((self.marked, self.typed), ([], []))
                self.assertEqual(self.health(name), {})
                self.assertEqual(self.typed, [])
                self.auth.assert_not_called()
                self.reset.assert_not_called()
                self.window.assert_not_called()

    def test_a_goal_stalled_on_a_recorded_error_is_resumed_by_its_own_command(self):
        # the record says why the turn failed, and the screen what starts the goal again
        for kind, text in ((CASES[5][1], CASES[5][3]),
                           ("usage_limit_exceeded", "You've hit your usage limit. Try again at "
                                                    "Jan 1st, 2027 10:32 PM.")):    # passed
            with self.subTest(text=text):
                name = self.record("codex", failed("codex", kind, None, text),
                                   f"{wrapped('codex', text)}\nGoal stalled")
                self.account(name)
                self.assertEqual((self.marked, self.typed), ([], ["/goal resume"]))

    def test_without_a_record_the_screen_is_read_as_before(self):
        # a seat whose harness has not written this conversation down yet
        name = self.record("claude", [], "⎿ API Error: 429 Usage limit reached")
        for path in (self.root / ".claude/projects").rglob("*.jsonl"):
            path.unlink()
        self.assertIsNone(watch.recorded_error("claude", name))
        self.assertEqual(watch.stalled_on("claude", self.pane, name, self.lines.append),
                         "Usage limit reached")
        self.account(name)
        self.assertEqual(self.marked, [("anthropic", None)])
        # one whose record cannot be read, not even where it is
        name = self.record("claude", failed("claude", *CASES[3][1:4]), self.pane)
        with patch.object(claude, "transcript", side_effect=PermissionError(13, "denied")):
            self.assertIsNone(watch.recorded_error("claude", name))
            self.assertEqual(watch.failed_on("claude", watch.content_lines("claude", self.pane),
                                             name), ("spent", "Usage limit reached"))
        # and a harness keeping a history but reading no error in it, whose screen still says
        self.harness, self.provider, self.seat["name"] = "grokbuild", "xai", "fix-api-grok"
        thread = "0d9b6c1e-5a2f-4c7e-9e1a-3f2b8c4d6aff"
        config.save_session(self.cfg, "fix-api-grok", "grok", ["grok"], {
            "cwd": str(self.work), "conversation": thread, "id_source": orch.LAUNCHER})
        history = (self.root / ".grok/sessions" / quote(str(self.work), safe="") / thread
                   / "chat_history.jsonl")
        history.parent.mkdir(parents=True)
        history.write_text(json.dumps({"role": "user", "content": "Fix the API."}) + "\n")
        record = config.session_records()["fix-api-grok"]
        self.assertEqual(orch.harness_plugin("grokbuild").transcript(record, None, thread),
                         str(history))
        self.assertIsNone(watch.recorded_error("grokbuild", "fix-api-grok"))
        pane = "Error: quota exceeded"
        self.assertEqual(watch.failed_on("grokbuild", watch.content_lines("grokbuild", pane),
                                         "fix-api-grok"), ("spent", "quota exceeded"))
        pane = "Session expired. Run `grok login` to re-authenticate."
        self.assertTrue(watch.auth_expired_on("grokbuild", pane, "fix-api-grok"))
        self.assertTrue(watch.stuck_on("grokbuild", pane, "fix-api-grok"))


if __name__ == "__main__":
    unittest.main()
