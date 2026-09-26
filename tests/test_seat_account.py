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

    def answer(self):
        return watch.session_state(NAME, session=self.seat, cfg=self.cfg, records=[])

    def test_spent_account_reopens_same_conversation_and_keeps_everything_owned(self):
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
        self.assertIn(f"CLAUDE_CONFIG_DIR={self.root}/.claude-second", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], CONVERSATION)
        self.assertEqual((self.root / ".claude-second/projects").resolve(),
                         self.root / ".claude/projects")
        watch.continue_turns(self.cfg, self.logs.append)
        watch.continue_turns(self.cfg, self.logs.append)
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
        # Looking, opening and new screen output cannot end the wait. Only reopening can.
        self.pane = "❯"
        watch.opened_now(NAME)
        self.assertEqual(self.answer()["reason"], answer["reason"])
        self.meters(100, 0)
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertIsNone(watch.seat_read(NAME)["usage_wait"])

    def test_interactive_command_uses_the_selected_login_and_clears_inherited_token(self):
        fake = self.root / "fake-claude"
        fake.write_text('#!/usr/bin/env python3\nimport json, os\n'
                        'print(json.dumps({k: os.environ.get(k) for k in '
                        '["AGENTKIT_ACCOUNT", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN"]}))\n')
        fake.chmod(0o755)
        for account in ("second", "default"):
            cmd = orch.resume_command(self.cfg, "opus", CONVERSATION, self.root,
                                      seat=NAME, account=account)
            # Replace only the wrappers/harness, keeping the adapter's real env command.
            cmd = cmd[:cmd.index("python3")] + [str(fake)]
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True,
                                  env={**os.environ, "CLAUDE_CONFIG_DIR": "/wrong-account",
                                       "CLAUDE_CODE_OAUTH_TOKEN": "wrong-token"})
            result = json.loads(proc.stdout)
            self.assertEqual(result["AGENTKIT_ACCOUNT"], "" if account == "default" else account)
            suffix = "" if account == "default" else "-second"
            self.assertEqual(result["CLAUDE_CONFIG_DIR"], str(self.root / f".claude{suffix}"))
            self.assertIsNone(result["CLAUDE_CODE_OAUTH_TOKEN"])

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

    def test_screen_refusal_marks_only_its_account_despite_meters_with_room(self):
        self.meters(20, 40)
        self.pane = "Usage limit reached"
        self.tick()
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

    def test_codex_refusal_waits_for_its_deadline_and_resumes_the_owned_thread(self):
        config.save_session(self.cfg, NAME, "astra", ["opus"], {"cwd": str(self.root)})
        transcript = self.root / "rollout.jsonl"
        transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "cwd": str(self.root), "id": CONVERSATION}}) + "\n")
        receipt = codex.prepare(NAME, self.root, None)
        codex.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
            "session_id": CONVERSATION, "transcript_path": str(transcript), "cwd": str(self.root)})
        until = self.now + 180
        self.pane = ("You've hit your usage limit. Try again at " +
                     time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
        self.tick()
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


if __name__ == "__main__":
    unittest.main()
