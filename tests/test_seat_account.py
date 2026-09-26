"""A seat keeps its conversation when its provider's next subscription takes over; offline."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, usage, watch
from agentkit.harness import codex
from agentkit.worker import auth_ok

NAME = "fix-api"
CONVERSATION = "d6fae368-678c-444e-8032-9c5c5338c84e"


class SeatAccount(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".seat-account-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        home = self.root / ".agentkit"
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, key, home / key.lower()))
        self.stack.enter_context(patch.object(config, "HOME", home))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AK_", "AGENTKIT_"))
               and k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "CODEX_HOME")}
        env.update(HOME=str(self.root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AK_RUN_ROLE="orchestrator", AGENTKIT_DISCORD_WEBHOOK="off",
                   AGENTKIT_TMUX_SOCKET="agentkit-test", AK_NOTIFY_SINK=str(self.root / "notices"))
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        config_text = (REPO / "config.default.toml").read_text().replace(
            "[providers.anthropic]", '[providers.anthropic]\naccounts = ["default", "second"]')
        (config.HOME / "config.toml").write_text(config_text)
        self.cfg = config.load()
        self.now = 1_800_000_000
        self.stack.enter_context(patch.object(time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(watch.time, "sleep"))
        self.stack.enter_context(patch.object(watch, "boot_id", return_value="test-boot"))
        self.stack.enter_context(patch.object(watch, "poll_worker_token"))
        self.auth = self.stack.enter_context(patch.object(watch.worker, "auth_ok",
                                                         return_value=(True, "fake seat login")))
        self.stack.enter_context(patch.object(usage, "_probe",
            side_effect=AssertionError("no real usage probes")))
        self.seat = {"name": NAME, "path": str(self.root), "created": self.now - 60,
                     "attached": False, "exited": False, "legacy": False}
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "dress"))
        self.stack.enter_context(patch.object(watch, "pane_text", side_effect=lambda _: self.pane))
        self.pane = "❯"
        self.stack.enter_context(patch.object(watch, "type_into", side_effect=self.type_into))
        self.commands, self.typed, self.logs = [], [], []
        config.save_session(self.cfg, NAME, "opus", ["opus", "astra"], {
            "cwd": str(self.root), "repo": str(self.root), "created": self.now - 60,
            "conversation": CONVERSATION, "id_source": orch.LAUNCHER, "account": "default"})
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        transcript = self.root / ".claude/projects" / slug / f"{CONVERSATION}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text('{"message":"unfinished task"}\n')
        config.plan_path(NAME).write_text("- [ ] Finish the endpoint\n")
        config.card_path(NAME).write_text('{"word":"working","episode":"keep-me"}\n')
        self.meters(100, 20)

    def meters(self, first, second, single=False):
        def reading(used, reset):
            return {"provider": "anthropic", "resets": 0, "meters": [usage._normalized({
                "name": "weekly_all", "used": used, "resets_at": reset,
                "window_secs": 604800}, self.now)]}
        first = reading(first, self.now + 86400)
        second = reading(second, self.now + 3600)
        anthropic = first if single else {**first, "accounts": {"default": first, "second": second}}
        providers = {"anthropic": anthropic, "openai": {"resets": 0, "meters": []}}
        (config.STATE / "usage.json").write_text(json.dumps({
            "fetched_at": self.now, "reset_checked_at": self.now, "providers": providers}))

    def tmux(self, *args, **kwargs):
        if args[0] == "respawn-pane":
            self.commands.append(shlex.split(args[-1]))
            self.pane = "❯"
        return 0, ""

    def type_into(self, session, text, log, stale=lambda _: False):
        if stale(session["name"]):
            return False
        self.typed.append(text)
        return True

    def tick(self, dry=False):
        state = watch.load_state()
        watch.health(self.cfg, state, dry, self.logs.append)
        if not dry:
            watch.save_state(state)

    def refusal_tick(self):
        self.tick()
        self.assertEqual(self.commands, [])
        self.now += watch.STALL_WAIT
        self.tick()

    def cached(self, change):
        path = config.STATE / "usage.json"
        data = json.loads(path.read_text())
        change(data["providers"])
        path.write_text(json.dumps(data))

    def answer(self):
        return watch.session_state(NAME, session=self.seat, cfg=self.cfg, records=[])

    def test_spent_account_reopens_same_conversation_and_keeps_everything_owned(self):
        self.pane = "Usage limit reached"
        before = config.session_records()[NAME]
        plan = config.plan_path(NAME).read_bytes()
        card = config.card_path(NAME).read_bytes()
        self.tick()
        after = config.session_records()[NAME]
        self.assertEqual(after["account"], "second")
        for key in ("conversation", "orchestrator", "workers", "cwd", "repo", "created"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(config.plan_path(NAME).read_bytes(), plan)
        self.assertEqual(config.card_path(NAME).read_bytes(), card)
        cmd = self.commands[0]
        self.assertIn("AGENTKIT_ACCOUNT=second", cmd)
        self.assertIn(str(REPO / "agentkit/harness/claude.py"), cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], CONVERSATION)
        self.assertEqual((self.root / ".claude-second/projects").resolve(),
                         self.root / ".claude/projects")
        watch.continue_turns(self.cfg, self.logs.append, accounts=True)
        watch.continue_turns(self.cfg, self.logs.append, accounts=True)
        self.assertEqual(self.typed, [watch.ACCOUNT_LINE])
        self.tick()
        self.assertEqual(len(self.commands), 1)

    def test_all_accounts_spent_needs_you_once_with_reset_and_never_changes_provider(self):
        self.meters(100, 100)
        self.tick()
        answer = self.answer()
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.now + 3600))
        self.assertEqual((answer["word"], answer["reason"]),
                         ("needs you", f"anthropic out of usage until {when}"))
        with patch.object(notify, "_history", return_value=False), \
                patch.object(notify, "terminal_notice"):
            notify.transition(NAME, seat=self.seat, answer=answer)
            self.now += notify.CARD_WAIT + 1
            notify.transition(NAME, seat=self.seat, answer=answer)
            notify.transition(NAME, seat=self.seat, answer=answer)
        self.assertEqual(len(list(notify.outbox().glob("*.json"))), 1)
        self.tick()
        self.assertEqual(self.answer(), answer)
        self.assertEqual(len([line for line in self.logs if "out of usage" in line]), 1)
        self.assertEqual(self.commands, [])
        self.assertEqual(config.session_records()[NAME]["orchestrator"], "opus")
        # Looking and new screen output cannot end the wait.
        self.pane = "❯"
        watch.live_state(self.seat, "claude", pane=self.pane, cfg=self.cfg)
        self.assertEqual(self.answer()["reason"], answer["reason"])
        self.meters(100, 0)
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertIsNone(watch.seat_read(NAME)["usage_wait"])

    def test_claude_account_launch_keeps_trust_hooks_and_the_selected_login(self):
        subprocess.run([str(REPO / "adapters/claude.sh"), "hooks"], check=True,
                       capture_output=True, env=os.environ)
        second = self.root / ".claude-second"
        second.mkdir()
        (second / ".claude.json").write_text('{"oauthAccount":{"accountUuid":"second"}}')
        (second / "settings.json").write_text('{"custom":"keep"}')
        settings = self.root / ".claude/settings.json"
        shared = json.loads(settings.read_text())
        shared.update(permissions={"allow": ["Read"]}, env={"ACME_MODE": "test"},
                      statusLine={"type": "command", "command": "acme-status"})
        settings.write_text(json.dumps(shared))
        for name in ("CLAUDE.md", "agents", "skills", "commands", "plugins"):
            source = self.root / ".claude" / name
            if name == "CLAUDE.md":
                source.write_text("Use the project conventions.\n")
            else:
                source.mkdir()
        fake = self.root / "fake-claude"
        fake.write_text('''#!/usr/bin/env python3
import json, os
from pathlib import Path
home = Path.home()
directory = os.environ.get("CLAUDE_CONFIG_DIR")
global_config = Path(directory) / ".claude.json" if directory else home / ".claude.json"
settings = Path(directory) if directory else home / ".claude"
print(json.dumps({"account": os.environ.get("AGENTKIT_ACCOUNT"), "directory": directory,
    "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
    "global": json.loads(global_config.read_text()),
    "settings": json.loads((settings / "settings.json").read_text())}))
''')
        fake.chmod(0o755)
        for account in ("second", "default", None):
            cmd = orch.resume_command(self.cfg, "opus", CONVERSATION, self.root,
                                      seat=NAME, account=account)
            # Run all real trust/account preparation; replace only the compactor and TUI.
            at = cmd.index(str(REPO / "tools/idle-compact.py")) - 1
            proc = subprocess.run(cmd[:at] + [str(fake)], check=True, cwd=self.root,
                                  capture_output=True, text=True, env={**os.environ,
                                  "CLAUDE_CONFIG_DIR": "/wrong-account",
                                  "CLAUDE_CODE_OAUTH_TOKEN": "wrong-token"})
            result = json.loads(proc.stdout)
            self.assertEqual(result["directory"], str(second) if account == "second" else None)
            self.assertIsNone(result["token"])
            self.assertTrue(result["global"]["hasCompletedOnboarding"])
            self.assertTrue(result["global"]["projects"][str(self.root)]["hasTrustDialogAccepted"])
            hooks = result["settings"]["hooks"]
            for event in ("UserPromptSubmit", "Stop", "Notification"):
                self.assertIn("seat-state.sh", json.dumps(hooks[event]))
            self.assertIn("orchestrator-stop.sh", json.dumps(hooks["Stop"]))
            for key in ("permissions", "env", "statusLine"):
                self.assertEqual(result["settings"][key], shared[key])
            if account == "second":
                self.assertEqual(result["settings"]["custom"], "keep")
                self.assertEqual(result["global"]["oauthAccount"]["accountUuid"], "second")
                for name in ("CLAUDE.md", "agents", "skills", "commands", "plugins"):
                    self.assertEqual((second / name).resolve(), self.root / ".claude" / name)
        shared["hooks"] = {"Stop": [{"hooks": [{"type": "command", "command": "new-hook"}]}]}
        settings.write_text(json.dumps(shared))
        with patch.dict(os.environ, {"AGENTKIT_ACCOUNT": "second"}):
            from agentkit.harness.claude import account_config
            account_config()
        self.assertEqual(json.loads((second / "settings.json").read_text())["hooks"], shared["hooks"])

    def test_invalid_claude_settings_leave_the_existing_pane_running(self):
        (self.root / ".claude/settings.json").write_text("not json")
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertEqual(config.session_records()[NAME]["account"], "default")
        self.assertIn("account reopen failed", self.answer()["reason"])

    def test_failed_reopen_keeps_the_account_and_retries_with_the_conversation(self):
        with patch.object(orch, "tmux_out", return_value=(1, "fake launch failure")):
            self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "default")
        self.assertEqual(self.answer()["word"], "needs you")
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertIn(CONVERSATION, self.commands[0])

    def test_account_with_room_is_left_alone_even_when_another_has_more(self):
        self.meters(40, 0)
        before = config.session_records()[NAME]
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.typed, [])
        self.assertEqual(config.session_records()[NAME], before)

    def test_worker_token_alone_never_receives_a_seat_and_login_allows_recovery(self):
        (config.SECRETS / "claude_oauth_token.second").write_text("fake-worker-token")
        self.assertTrue(auth_ok("claude", account="second")[0])
        self.assertFalse(auth_ok("claude", seat=True, account="second")[0])
        self.auth.side_effect = auth_ok
        self.tick()
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertEqual(config.session_records()[NAME]["account"], "default")
        self.assertEqual(self.answer()["word"], "needs you")
        self.assertEqual(len([line for line in self.logs if "out of usage" in line]), 1)
        credentials = self.root / ".claude-second/.credentials.json"
        credentials.parent.mkdir()
        credentials.write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "fake-seat-token", "expiresAt": 4_102_444_800_000}}))
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertIn(CONVERSATION, self.commands[0])
        self.assertIsNone(watch.seat_read(NAME)["usage_wait"])

    def test_unanswered_seat_login_is_skipped_for_another_of_the_same_provider(self):
        self.cfg["providers"]["anthropic"]["accounts"].append("third")
        self.cached(lambda p: p["anthropic"]["accounts"].update(
            third=p["anthropic"]["accounts"]["second"]))
        self.auth.side_effect = lambda harness, seat=False, account=None: (
            None if account == "second" else True, "fake seat login")
        self.tick()
        self.auth.assert_any_call("claude", seat=True, account="second")
        self.auth.assert_any_call("claude", seat=True, account="third")
        self.assertEqual(config.session_records()[NAME]["account"], "third")
        self.assertIn(CONVERSATION, self.commands[0])

    def test_owner_typing_during_seat_login_check_prevents_reopening(self):
        def login(*args, **kwargs):
            self.pane = "❯ the owner is typing"
            return True, "fake seat login"
        self.auth.side_effect = login
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))

    def test_screen_refusal_marks_only_its_account_despite_meters_with_room(self):
        self.meters(20, 40)
        self.pane = "Usage limit reached"
        self.refusal_tick()
        providers = usage.collect(self.cfg)
        self.assertTrue(providers["anthropic"]["accounts"]["default"]["exhausted"])
        self.assertFalse(providers["anthropic"]["accounts"]["second"]["exhausted"])
        self.assertEqual(config.session_records()[NAME]["account"], "second")

    def test_single_subscription_waits_and_reopens_itself_when_usage_returns(self):
        self.cfg["providers"]["anthropic"].pop("accounts")
        self.meters(100, 0, single=True)
        self.tick()
        self.assertEqual(self.answer()["word"], "needs you")
        self.meters(0, 0, single=True)
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "default")
        self.assertEqual(len(self.commands), 1)

    def test_preview_and_owner_closed_seats_never_reopen(self):
        before = config.session_records()[NAME]
        self.tick(dry=True)
        self.assertEqual(config.session_records()[NAME], before)
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))
        watch.seat_write(NAME, closed_by_owner=self.now)
        self.tick()
        self.assertEqual(self.commands, [])

    def test_owner_stopping_during_meter_io_wins_over_automatic_reopen(self):
        collect = usage.collect
        def stopped(cfg):
            readings = collect(cfg)
            orch.mark_owner_closed(NAME)
            return readings
        with patch.object(usage, "collect", side_effect=stopped):
            self.tick()
        self.assertEqual(self.commands, [])
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))

    def test_codex_refusal_waits_for_its_deadline_and_resumes_the_owned_thread(self):
        config.save_session(self.cfg, NAME, "astra", ["opus"], {"cwd": str(self.root)})
        transcript = self.root / "rollout.jsonl"
        transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "cwd": str(self.root), "id": CONVERSATION}}) + "\n")
        receipt = codex.prepare(NAME, self.root, None)
        codex.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
            "session_id": CONVERSATION, "transcript_path": str(transcript), "cwd": str(self.root)})
        until = self.now + 240
        self.pane = ("You've hit your usage limit. Try again at " +
                     time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
        self.refusal_tick()
        self.assertEqual(usage.collect(self.cfg)["openai"]["exhausted_until"], until)
        self.assertIn("openai out of usage until", self.answer()["reason"])
        self.assertEqual(self.commands, [])
        self.now = until + 1
        # The old refusal remains on screen: it must not park the reset window again.
        self.tick()
        self.assertEqual(len(self.commands), 1)
        cmd = self.commands[0]
        self.assertEqual(cmd[cmd.index("resume") + 1], CONVERSATION)
        self.assertEqual(orch.seat_conversation(config.session_records()[NAME]), CONVERSATION)

    def test_new_seat_records_its_selected_account_and_manual_resume_keeps_it(self):
        with patch.object(orch, "start"):
            orch.create(self.cfg, "new-api", self.root,
                        selection=(usage.collect(self.cfg), ("opus", "chosen", ["astra"])))
        self.assertEqual(config.session_records()["new-api"]["account"], "second")
        self.tick()
        self.seat["exited"] = True
        orch.resume(self.cfg, NAME, hand_over=False, log=self.logs.append)
        self.assertIn("AGENTKIT_ACCOUNT=second", self.commands[-1])

    def scoped_meters(self):
        def add(providers):
            for reading in providers["anthropic"]["accounts"].values():
                reading["meters"].append(usage._normalized({"name": "weekly_scoped", "used": 100,
                    "resets_at": self.now + 604800, "window_secs": 604800}, self.now))
        self.cached(add)

    def test_other_models_scoped_meter_never_spends_this_seat_or_its_next_account(self):
        self.meters(50, 50)
        self.scoped_meters()
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))
        self.meters(100, 50)
        self.scoped_meters()
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")

    def test_reset_deadline_ignores_other_models_scoped_meter(self):
        self.meters(100, 100)
        self.scoped_meters()
        self.tick()
        self.assertEqual(watch.seat_read(NAME)["usage_wait"]["until"], self.now + 3600)

    def test_new_seat_also_selects_accounts_using_its_own_model_meters(self):
        self.meters(30, 80)
        self.scoped_meters()
        self.cached(lambda p: p["anthropic"]["accounts"]["second"]["meters"][-1].update(used=0))
        self.cached(lambda p: p["anthropic"]["accounts"]["second"]["meters"][0].update(
            resets_at=self.now + 86400))
        providers = usage.collect(self.cfg)
        self.assertEqual(providers["anthropic"]["account"], "second")
        with patch.object(orch, "start"):
            orch.create(self.cfg, "new-api", self.root,
                        selection=(providers, ("opus", "chosen", ["astra"])))
        self.assertEqual(config.session_records()["new-api"]["account"], "default")

    def test_unowned_conversations_continue_in_place_after_their_account_refills(self):
        for model, provider in (("astra", "openai"), ("spark", "meta"), ("gemini", "google")):
            with self.subTest(model=model):
                self.pane = "RESOURCE_EXHAUSTED" if model == "gemini" else "Usage limit reached"
                config.save_session(self.cfg, NAME, model, ["opus"], {"cwd": str(self.root)})
                self.cached(lambda p: p.update({provider: {
                    "resets": 0, "meters": [], "exhausted_until": self.now + 60}}))
                self.tick()
                self.assertIn(f"{provider} out of usage until", self.answer()["reason"])
                self.now += 61
                self.tick()
                self.assertIsNone(watch.seat_read(NAME)["usage_wait"])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.typed, ["continue"] * 3)
        self.assertFalse(any("WARN" in line for line in self.logs))

    def test_transient_rate_limit_never_parks_an_account(self):
        self.meters(30, 20)
        self.pane = "API Error: 429 rate limit"
        self.tick()
        self.assertEqual(self.typed, [])
        self.now += watch.STALL_WAIT
        self.tick()
        self.assertEqual(self.typed, ["continue"])
        self.assertFalse(usage.collect(self.cfg)["anthropic"]["accounts"]["default"]["exhausted"])
        self.assertEqual(self.commands, [])
        self.now += watch.GIVE_UP
        self.meters(30, 20)
        with patch.object(notify, "shaped", return_value=0) as shaped:
            self.tick()
            self.tick()
        self.assertEqual(shaped.call_count, 1)
        self.assertEqual(self.typed, ["continue"])
        self.assertFalse(usage.collect(self.cfg)["anthropic"]["accounts"]["default"]["exhausted"])

    def test_refusal_that_disappears_before_stall_wait_spends_nothing(self):
        self.meters(30, 20)
        self.pane = "Usage limit reached"
        self.tick()
        self.pane = "Reading the next file"
        self.now += watch.STALL_WAIT
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertFalse(watch.seat_read(NAME).get("usage_refusal"))
        self.assertFalse(usage.collect(self.cfg)["anthropic"]["accounts"]["default"]["exhausted"])

    def test_pending_continue_does_not_spend_the_new_account_on_old_transcript_text(self):
        self.pane = "Usage limit reached"
        self.tick()
        self.pane = "Usage limit reached"
        with patch.object(watch, "type_into", return_value=False):
            watch.continue_turns(self.cfg, self.logs.append, accounts=True)
        self.now += watch.STALL_WAIT
        self.tick()
        self.assertFalse(usage.collect(self.cfg)["anthropic"]["accounts"]["second"]["exhausted"])
        self.assertEqual(len(self.commands), 1)
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))

    def test_refusal_deadline_comes_only_from_the_current_output_line(self):
        config.save_session(self.cfg, NAME, "astra", ["opus"], {"cwd": str(self.root)})
        until = self.now + 240
        self.pane = ("You've hit your usage limit. Try again at " +
                     time.strftime("%Y-%m-%d %H:%M", time.localtime(self.now + 86400)) +
                     "\nOld message ended\nYou've hit your usage limit. Try again at " +
                     time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
        self.refusal_tick()
        self.assertEqual(usage.collect(self.cfg)["openai"]["exhausted_until"], until)

    def test_usage_failure_does_not_abort_health_for_the_next_seat(self):
        later = {**self.seat, "name": "next-api"}
        config.save_session(self.cfg, later["name"], "opus", ["astra"], {
            "cwd": str(self.root), "conversation": CONVERSATION, "id_source": orch.LAUNCHER})
        collect = usage.collect
        calls = []
        def readings(cfg):
            calls.append(cfg)
            if len(calls) == 1:
                raise config.Error("fake meter failure")
            return collect(cfg)
        with patch.object(orch, "sessions", return_value=[self.seat, later]), \
                patch.object(usage, "collect", side_effect=readings):
            self.tick()
        self.assertEqual(config.session_records()[later["name"]]["account"], "second")
        self.assertEqual(config.session_records()[NAME]["account"], "default")

    def test_opening_to_look_preserves_recovery_but_a_draft_prevents_respawning(self):
        self.meters(100, 100)
        self.tick()
        watch.opened_now(NAME)
        self.assertIsNotNone(watch.seat_read(NAME)["usage_wait"])
        watch.opened_now(NAME)
        self.meters(100, 0)
        self.pane = "❯ the owner is typing"
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.typed, [])
        self.pane = "❯"
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertFalse(watch.seat_read(NAME).get("midturn"))

    def test_refusal_on_a_refilled_account_is_consumed_even_after_owner_opens(self):
        for deadline in (None, self.now - 21600):
            with self.subTest(deadline=deadline):
                self.meters(100, 100)
                self.pane = "Usage limit reached"
                if deadline:
                    self.pane += " Try again at " + time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(deadline))
                old = self.pane
                self.tick()
                watch.opened_now(NAME)
                self.meters(0, 100)
                self.tick()
                watch.continue_turns(self.cfg, self.logs.append, accounts=True)
                self.pane = old
                for _ in range(3):
                    self.now += watch.STALL_WAIT
                    # Keep the fake meter probe current without overwriting a park.
                    path = config.STATE / "usage.json"
                    data = json.loads(path.read_text())
                    data["fetched_at"] = self.now
                    path.write_text(json.dumps(data))
                    self.tick()
                    self.assertFalse(usage.collect(self.cfg)["anthropic"]["accounts"]["default"]["exhausted"])
                    self.assertFalse(watch.seat_read(NAME).get("usage_wait"))

    def test_past_codex_deadline_never_parks_usage_or_respawns_the_seat(self):
        config.save_session(self.cfg, NAME, "astra", ["opus"], {"cwd": str(self.root)})
        self.pane = "You've hit your usage limit. Try again at " + time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(self.now - 21600))
        self.refusal_tick()
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.typed, ["continue"])
        self.assertFalse(usage.collect(self.cfg)["openai"]["exhausted"])
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))

    def test_exited_seats_never_reopen_on_quota(self):
        self.seat["exited"] = True
        self.tick()
        self.assertEqual(self.commands, [])
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))

    def test_owner_quitting_or_typing_during_meter_io_wins(self):
        collect = usage.collect
        for action in (lambda: self.seat.update(exited=True),
                       lambda: setattr(self, "pane", "❯ the owner is typing")):
            self.seat["exited"] = False
            self.pane = "❯"
            def readings(cfg):
                result = collect(cfg)
                action()
                return result
            with patch.object(usage, "collect", side_effect=readings):
                self.tick()
        self.assertEqual(self.commands, [])

    def test_account_continue_waits_for_a_draft_and_never_claims_a_fresh_resume(self):
        self.pane = "Usage limit reached"
        with patch.object(orch, "resume", return_value="fresh"):
            self.tick()
        self.assertFalse(watch.seat_read(NAME).get("midturn"))
        self.tick()
        self.pane = "❯ the owner is typing"
        watch.continue_turns(self.cfg, self.logs.append, accounts=True)
        self.assertEqual(self.typed, [])
        self.assertTrue(watch.seat_read(NAME).get("midturn"))
        self.pane = "❯"
        watch.continue_turns(self.cfg, self.logs.append, accounts=True)
        self.assertEqual(self.typed, [watch.ACCOUNT_LINE])

    def test_meter_recovery_at_an_idle_prompt_does_not_start_a_turn(self):
        self.tick()
        watch.continue_turns(self.cfg, self.logs.append, accounts=True)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.typed, [])
        config.save_session(self.cfg, NAME, "astra", ["opus"], {"cwd": str(self.root)})
        self.cached(lambda p: p["openai"].update(exhausted_until=self.now + 60))
        self.tick()
        self.now += 61
        self.tick()
        self.assertFalse(watch.seat_read(NAME).get("usage_wait"))
        self.assertEqual(self.typed, [])

    def test_unknown_reset_never_reuses_a_past_deadline(self):
        self.meters(100, 100)
        self.cached(lambda p: [a["meters"][0].update(resets_at=None)
                              for a in p["anthropic"]["accounts"].values()])
        watch.seat_write(NAME, usage_wait={"reason": "old wait", "since": self.now - 3600,
                                          "until": self.now - 60})
        self.tick()
        self.assertGreater(watch.seat_read(NAME)["usage_wait"]["until"], self.now)

    def test_manual_resume_and_owner_close_end_the_usage_wait(self):
        self.meters(100, 100)
        self.tick()
        self.seat["exited"] = True
        self.assertNotIn("out of usage", self.answer()["reason"])
        orch.resume(self.cfg, NAME, hand_over=False, log=self.logs.append)
        self.assertIsNone(watch.seat_read(NAME)["usage_wait"])
        self.seat["exited"] = False
        self.tick()
        orch.mark_owner_closed(NAME)
        self.seat["exited"] = True
        self.assertIsNone(watch.seat_read(NAME)["usage_wait"])
        self.assertNotIn("out of usage", self.answer()["reason"])

    def test_codex_command_uses_a_separate_file_login_and_shared_conversations(self):
        fake = self.root / "fake-codex"
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
print(json.dumps({"login": json.loads((home / "auth.json").read_text()), "args": sys.argv,
    "key": os.environ.get("OPENAI_API_KEY"), "exec_key": os.environ.get("CODEX_API_KEY")}))
''')
        fake.chmod(0o755)
        base = self.root / ".codex"
        base.mkdir()
        (base / "config.toml").write_text('model = "test-model"\n')
        custom = self.root / "custom-codex"
        custom.mkdir()
        (custom / "auth.json").write_text('{"account":"default"}')
        for account in ("default", None, "second"):
            login = account or "default"
            folder = self.root / (".codex" if login == "default" else ".codex-second")
            folder.mkdir(exist_ok=True)
            (folder / "auth.json").write_text(json.dumps({"account": login}))
            cmd = orch.command(self.cfg, "astra", CONVERSATION, account=account)
            at = cmd.index(str(REPO / "tools/idle-compact.py")) - 1
            wrapper = cmd.index(str(REPO / "tools/codex-seat.py")) - 1
            cmd = cmd[:at] + cmd[wrapper:]
            harness = cmd.index("--", cmd.index(str(REPO / "tools/codex-seat.py"))) + 1
            cmd[harness] = str(fake)
            proc = subprocess.run(cmd, check=True, cwd=self.root, capture_output=True, text=True,
                env={**os.environ, "CODEX_HOME": str(custom), "OPENAI_API_KEY": "test-key",
                     "CODEX_API_KEY": "test-exec-key"})
            result = json.loads(proc.stdout)
            self.assertEqual(result["login"]["account"], login)
            self.assertIn(CONVERSATION, result["args"])
            self.assertEqual(result["key"], None if account == "second" else "test-key")
            self.assertEqual(result["exec_key"], None if account == "second" else "test-exec-key")
            if account == "second":
                self.assertIn('cli_auth_credentials_store="file"', result["args"])
                self.assertIn(f'projects."{self.root}".trust_level="trusted"', result["args"])
                self.assertEqual((folder / "sessions").resolve(), self.root / ".codex/sessions")
                self.assertEqual((folder / "config.toml").resolve(), base / "config.toml")


if __name__ == "__main__":
    unittest.main()
