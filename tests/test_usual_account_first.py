"""Seats stay on the usual subscription while it has room; workers use the others first.

Offline: a temporary HOME, fake meters in usage.json, fake tmux and adapters. No real
login, provider or endpoint is reached. Seat and project names are invented.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, usage, watch  # noqa: E402

NAME = "fix-api"
CONVERSATION = "d6fae368-678c-444e-8032-9c5c5338c84e"


class UsualAccountFirst(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".usual-first-", dir=REPO)
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
        self.stack.enter_context(patch.object(watch.worker, "auth_ok",
                                              return_value=(True, "fake seat login")))
        self.stack.enter_context(patch.object(usage, "replenish", return_value=(False, 0)))
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
        self.meters(40, 0)

    def meters(self, first, second, third=None):
        def reading(used, reset):
            return {"provider": "anthropic", "resets": 0, "meters": [usage._normalized({
                "name": "weekly_all", "used": used, "resets_at": reset,
                "window_secs": 604800}, self.now)]}
        first = reading(first, self.now + 86400)
        second = reading(second, self.now + 3600)
        anthropic = {**first, "accounts": {"default": first, "second": second,
                                           **({"third": reading(third, self.now + 3600)}
                                              if third is not None else {})}}
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

    def tick(self):
        state = watch.load_state()
        watch.health(self.cfg, state, False, self.logs.append)
        watch.save_state(state)

    def test_new_seat_opens_on_the_usual_account_while_it_has_room(self):
        self.meters(40, 0)
        with patch.object(orch, "start"):
            orch.create(self.cfg, "new-api", self.root,
                        selection=(usage.collect(self.cfg), ("opus", "chosen", ["astra"])))
        self.assertEqual(config.session_records()["new-api"]["account"], "default")
        self.meters(100, 20)
        with patch.object(orch, "start"):
            orch.create(self.cfg, "spill-api", self.root,
                        selection=(usage.collect(self.cfg), ("opus", "chosen", ["astra"])))
        self.assertEqual(config.session_records()["spill-api"]["account"], "second")

    def test_idle_seat_comes_home_and_a_busy_one_stays_until_it_is_idle(self):
        config.save_session(self.cfg, NAME, "opus", ["opus", "astra"], {
            "cwd": str(self.root), "repo": str(self.root), "created": self.now - 60,
            "conversation": CONVERSATION, "id_source": orch.LAUNCHER, "account": "second"})
        self.meters(0, 20)
        with patch.object(watch, "_turn_in_flight", return_value=(True, self.now)):
            self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual(self.commands, [])
        self.pane = "❯ the owner is typing"
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual(self.commands, [])
        self.pane = "❯"
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "default")
        self.assertEqual(len(self.commands), 1)
        self.assertIn(CONVERSATION, self.commands[0])
        self.assertIn("AGENTKIT_ACCOUNT=", self.commands[0])
        self.assertEqual(self.typed, [])

    def seat_account(self, account, listed='"default", "second"'):
        path = config.HOME / "config.toml"
        path.write_text(path.read_text().replace(
            'accounts = ["default", "second"]', f'seat_account = "{account}"\naccounts = [{listed}]'))
        self.cfg = config.load()

    def test_new_seats_open_on_the_named_seat_account_while_it_has_room(self):
        self.seat_account("second")
        self.meters(0, 40)
        with patch.object(orch, "start"):
            orch.create(self.cfg, "new-api", self.root,
                        selection=(usage.collect(self.cfg), ("opus", "chosen", ["astra"])))
        record = config.session_records()["new-api"]
        self.assertEqual((record["account"], record.get("home_account")), ("second", "second"))
        # A model switch to this provider opens its seat anew, on the same account.
        config.save_session(self.cfg, "fix-ui", "astra", ["astra"], {
            "cwd": str(self.root), "created": self.now - 60})
        with patch.object(config, "harness_binary", return_value="/bin/true"), \
                patch.object(orch, "launch"):
            self.assertEqual(orch.switch_orchestrator(self.cfg, "fix-ui", "opus"), "")
        record = config.session_records()["fix-ui"]
        self.assertEqual((record["account"], record.get("home_account")), ("second", "second"))
        # So does the seat a question to the owner opens by itself.
        with patch.object(orch, "launch"):
            self.assertTrue(orch.ensure(self.cfg, "inbox-api", log=self.logs.append))
        record = config.session_records()["inbox-api"]
        self.assertEqual((record.get("account"), record.get("home_account")), ("second", "second"))
        self.meters(0, 100)
        with patch.object(orch, "start"):
            orch.create(self.cfg, "spill-api", self.root,
                        selection=(usage.collect(self.cfg), ("opus", "chosen", ["astra"])))
        record = config.session_records()["spill-api"]
        self.assertEqual((record["account"], record.get("home_account")), ("default", "default"))

    def test_an_idle_seat_comes_back_to_the_account_it_opened_on(self):
        self.seat_account("second")
        self.meters(0, 20)
        # A record that names no home opened on the usual login, and stays there.
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "default")
        self.assertEqual(self.commands, [])
        config.update_session(NAME, home_account="second")
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "second")
        self.assertEqual(len(self.commands), 1)
        self.assertIn(CONVERSATION, self.commands[0])

    def test_a_spent_seat_moves_to_its_own_home_before_the_named_seat_account(self):
        self.seat_account("second", '"default", "second", "third"')
        config.update_session(NAME, account="third")
        self.meters(40, 0, 100)
        self.tick()
        self.assertEqual(config.session_records()[NAME]["account"], "default")
        self.assertEqual(len(self.commands), 1)

    def test_worker_turn_prefers_another_account_and_falls_back_to_the_usual(self):
        self.meters(40, 0)
        self.assertEqual(usage.account(self.cfg, "anthropic"), ("second", True))
        self.assertEqual(usage.collect(self.cfg)["anthropic"]["account"], "second")
        self.meters(40, 100)
        self.assertEqual(usage.account(self.cfg, "anthropic"), ("default", True))
        self.meters(100, 100)
        self.assertEqual(usage.account(self.cfg, "anthropic"), ("default", False))
        self.cfg["providers"]["anthropic"].pop("accounts")
        self.assertEqual(usage.account(self.cfg, "anthropic"), (None, None))


if __name__ == "__main__":
    unittest.main()
