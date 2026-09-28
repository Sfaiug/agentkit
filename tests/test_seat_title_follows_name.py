"""Seat renames need Claude's receipt; fake tmux and transcripts, a temporary HOME."""

from contextlib import redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, watch
from agentkit.harness import claude


class SeatTitle(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AK_NOTIFY_SINK": str(self.root / "notices")}))
        self.seat = {"name": "lagoon", "path": str(self.root), "created": 100,
                     "attached": True, "exited": False, "legacy": False}
        self.pane = self.fixture("prompt")
        self.commands, self.typed = [], []
        self.fail_send = False
        self.drop_enter = False
        self.wrap_at = 0
        self.confirm_title = True
        self.logs = []
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        self.stack.enter_context(patch.object(watch, "SENT_WAIT", watch.SENT_POLL))
        self.stack.enter_context(patch.object(watch.time, "sleep"))
        # Keep the health pass's unrelated recovery and notification work offline.
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))
        config.save_session(self.cfg, "lagoon", "opus", ["opus"], {
            "cwd": str(self.root), "session_title": "lagoon",
            "conversation": "fake-conversation", "id_source": orch.LAUNCHER})
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        self.transcript = self.root / ".claude/projects" / slug / "fake-conversation.jsonl"
        self.transcript.parent.mkdir(parents=True)
        self.transcript.touch()

    def title(self, name):
        with self.transcript.open("a") as handle:
            handle.write(json.dumps({"type": "custom-title", "customTitle": name,
                                     "sessionId": self.record()["conversation"]}) + "\n")

    def composer(self, text):
        width = self.wrap_at or len(text)
        return "❯ " + "\n  ".join(text[at:at + width] for at in range(0, len(text), width)) + "\n"

    def fixture(self, kind):
        return (REPO / "tests/fixtures" / f"claude-{kind}-pane.txt").read_text()

    def tmux(self, *args, **kwargs):
        self.commands.append(args)
        if args[0] == "rename-session":
            self.seat = dict(self.seat, name=args[-1])
        elif args[0] == "capture-pane":
            return 0, self.pane
        elif args[0] == "send-keys":
            self.assertEqual(args[2], f"={self.seat['name']}:")
            if self.fail_send:
                return 1, "fake send failure"
            if "-l" in args:
                self.typed.append(args[-1])
                self.pane = self.pane.replace("❯\u00a0\n", self.composer(args[-1]))
            elif args[-1] == "Enter" and not self.drop_enter:
                self.pane = self.pane.replace(self.composer(self.typed[-1]), "❯\u00a0\n")
                if self.confirm_title:
                    self.title(self.typed[-1].removeprefix("/rename "))
        return 0, ""

    def record(self):
        return config.session_records()[self.seat["name"]]

    def tick(self, dry=False):
        state = watch.load_state()
        watch.health(self.cfg, state, dry, self.logs.append)
        if not dry:
            watch.save_state(state)

    def test_rename_types_and_records_the_title_idle_or_mid_turn(self):
        for kind, name in (("prompt", "quay"), ("working", "harbor")):
            with self.subTest(kind=kind):
                self.pane = self.fixture(kind)
                old = self.seat["name"]
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(orch.cmd_rename([old, name]), 0)
                self.assertEqual(self.typed[-1], f"/rename {name}")
                self.assertEqual(self.record()["session_title"], name)
                before = list(self.typed)
                self.tick()
                self.assertEqual(self.typed, before)
        self.assertEqual(self.typed, ["/rename quay", "/rename harbor"])
        self.assertEqual(sum(args[-1] == "Enter" for args in self.commands), 2)

    def test_dialog_and_drafts_defer_until_a_later_tick(self):
        panes = [self.fixture("dialog"), self.fixture("draft"),
                 self.fixture("working").replace("❯\u00a0\n", "❯ Owner's unsent message\n")]
        for pane, name in zip(panes, ("quay", "harbor", "estuary")):
            with self.subTest(name=name):
                self.pane = pane
                title = self.record()["session_title"]
                before = list(self.typed)
                orch.rename(self.seat["name"], name)
                self.tick()
                self.assertEqual(self.typed, before)
                self.assertEqual(self.record()["session_title"], title)
                self.pane = self.fixture("prompt")
                self.tick()
                self.tick()
                self.assertEqual(self.typed, before + [f"/rename {name}"])
                self.assertEqual(self.record()["session_title"], name)

    def test_old_record_gets_one_line_on_tick(self):
        config.update_session("lagoon", session_title=None)
        self.tick()
        self.tick()
        self.assertEqual(self.typed, ["/rename lagoon"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_screen_is_checked_again_just_before_typing(self):
        config.update_session("lagoon", session_title=None)
        for kind in ("dialog", "draft"):
            with self.subTest(kind=kind), patch.object(watch, "pane_text", side_effect=[
                    self.fixture("prompt"), self.fixture(kind)]):
                self.assertFalse(watch.sync_title(self.seat))
                self.assertEqual(self.typed, [])
                self.assertNotIn("session_title", self.record())
        self.tick()
        self.assertEqual(self.typed, ["/rename lagoon"])

    def test_harness_without_a_title_gets_nothing(self):
        for model in ("astra", "spark"):
            with self.subTest(model=model):
                config.update_session(self.seat["name"], orchestrator=model, session_title=None)
                orch.rename(self.seat["name"], f"quay-{model}")
                self.tick()
                self.assertEqual(self.typed, [])
                self.assertNotIn("session_title", self.record())

    def test_launch_records_remote_control_title_without_typing(self):
        config.update_session("lagoon", session_title=None)
        cmd, conversation = orch.fresh_command(self.cfg, "opus", seat="lagoon")
        orch.launch("lagoon", "opus", self.root, cmd, conversation)
        self.assertEqual(cmd[cmd.index("--remote-control") + 1], "lagoon")
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.tick()
        self.assertEqual(self.typed, [])

    def test_renamed_seat_fresh_launch_does_not_retype_its_remote_control_title(self):
        orch.rename("lagoon", "reed", log=self.logs.append)
        before = len(self.commands)
        cmd, conversation = orch.fresh_command(self.cfg, "opus", seat="reed")
        orch.launch("reed", "opus", self.root, cmd, conversation, self.seat)
        self.assertEqual(cmd[cmd.index("--remote-control") + 1], "reed")
        self.assertEqual(self.record()["session_title"], "reed")
        self.tick()
        self.tick()
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))
        self.assertEqual(self.record()["session_title"], "reed")

    def test_renamed_seat_clear_does_not_retype_its_recorded_title(self):
        orch.rename("lagoon", "reed", log=self.logs.append)
        config.update_session("reed", conversation="next-conversation")
        self.transcript = self.transcript.with_name("next-conversation.jsonl")
        self.transcript.touch()
        before = len(self.commands)
        self.tick()
        self.tick()
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))
        self.assertEqual(self.record()["session_title"], "reed")

    def test_reconciled_conversation_does_not_retype_its_recorded_title(self):
        orch.rename("lagoon", "reed", log=self.logs.append)
        config.update_session("reed", id_source="unverified")
        self.assertNotIn("conversation", orch.records()["reed"])
        before = len(self.commands)
        self.tick()
        self.tick()
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))
        self.assertEqual(self.record()["session_title"], "reed")

    def test_resume_records_the_name_passed_to_remote_control(self):
        config.update_session("lagoon", conversation="fake-conversation", id_source=orch.LAUNCHER,
                              session_title="former-name",
                              title_sync={"name": "former-name", "tries": 3, "pending": True})
        self.seat["exited"] = True
        with patch.object(orch, "opened", return_value=True):
            self.assertEqual(orch.resume(self.cfg, "lagoon", log=lambda _: None,
                                         hand_over=False), "resumed")
        words = shlex.split(next(args[-1] for args in self.commands if args[0] == "respawn-pane"))
        self.assertEqual(words[words.index("--remote-control") + 1], "lagoon")
        self.assertEqual(self.record()["session_title"], "former-name")
        self.seat["exited"] = False
        self.pane = self.fixture("prompt").replace("❯\u00a0\n", self.composer("/rename former-name"))
        pane = self.pane
        self.tick()
        self.assertEqual(self.pane, pane)
        self.assertEqual(self.typed, [])

    def test_owner_question_defers_even_at_an_empty_prompt(self):
        notify.record("lagoon", "needs", "Which endpoint should this use?")
        orch.rename("lagoon", "quay")
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertEqual(self.record()["session_title"], "lagoon")
        config.notify_path("quay").unlink()
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])

    def test_closed_blank_unknown_and_dry_run_do_not_type(self):
        config.update_session("lagoon", session_title=None)
        for pane in ("", "$ "):
            self.pane = pane
            self.tick()
        self.pane = self.fixture("prompt")
        self.seat["exited"] = True
        self.tick()
        self.seat["exited"] = False
        self.tick(dry=True)
        self.assertEqual(self.typed, [])
        self.assertNotIn("session_title", self.record())

    def test_failed_send_leaves_title_pending_for_tick(self):
        self.fail_send = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.assertEqual(self.typed, [])
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.fail_send = False
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_dropped_enter_retries_only_the_enter(self):
        enters = []
        self.drop_enter = True

        def tmux(*args, **kwargs):
            answer = self.tmux(*args, **kwargs)
            if args[0] == "send-keys":
                if "-l" in args:
                    self.pane = f"❯ {args[-1]}"
                elif args[-1] == "Enter":
                    enters.append(True)
                    if len(enters) == 2:
                        self.pane = self.fixture("prompt")
                        self.title("quay")
            return answer

        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "SENT_WAIT", watch.SENT_POLL), \
                patch.object(watch.time, "sleep"):
            orch.rename("lagoon", "quay")
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(len(enters), 2)
        self.assertEqual(self.record()["session_title"], "quay")

    def test_dropped_enter_mid_turn_waits_for_a_receipt_and_next_tick_only_enters(self):
        self.pane = self.fixture("working")
        self.title("lagoon")
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertTrue(watch._holds_text(self.pane, "/rename quay"))
        self.assertEqual(self.typed, ["/rename quay"])
        before = len(self.commands)
        self.drop_enter = False
        self.tick()
        self.assertEqual([args[-1] for args in self.commands[before:]
                          if args[0] == "send-keys"], ["Enter"])
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.seat["name"], "quay")
        self.assertEqual(self.record()["session_title"], "quay")

    def test_wrapped_line_gets_its_enter_on_the_next_tick(self):
        self.wrap_at = 28
        self.drop_enter = True
        name = "quay-with-a-name-that-wraps-on-a-phone"
        orch.rename("lagoon", name, log=self.logs.append)
        self.assertIn(self.composer(f"/rename {name}"), self.pane)
        self.drop_enter = False
        before = len(self.commands)
        self.tick()
        self.assertEqual([args[-1] for args in self.commands[before:]
                          if args[0] == "send-keys"], ["Enter"])
        self.assertEqual(self.typed, [f"/rename {name}"])
        self.assertEqual(self.record()["session_title"], name)
        self.assertFalse(watch._holds_text(self.pane, f"/rename {name}"))

    def test_wrapped_line_gets_the_in_call_retry_enter(self):
        self.wrap_at = 10
        self.drop_enter = True

        def tmux(*args, **kwargs):
            answer = self.tmux(*args, **kwargs)
            if args[0] == "send-keys" and args[-1] == "Enter":
                self.drop_enter = False
            return answer

        with patch.object(orch, "tmux_out", side_effect=tmux):
            orch.rename("lagoon", "quay", log=self.logs.append)
        self.assertEqual(sum(args[-1] == "Enter" for args in self.commands), 2)
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_owner_text_after_a_wrapped_line_is_never_sent(self):
        self.wrap_at = 10
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.pane = self.pane.replace(self.composer("/rename quay"),
                                     self.composer("/rename quay-side"))
        pane = self.pane
        before = len(self.commands)
        self.tick()
        self.assertEqual(self.pane, pane)
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))

    def test_wrapped_dim_suggestion_does_not_block_title_sync(self):
        config.update_session("lagoon", session_title=None)
        self.pane = self.fixture("prompt").replace(
            "❯\u00a0\n", "❯ \x1b[2mTry checking the\x1b[0m\n  \x1b[2mparser next\x1b[0m\n")

        def tmux(*args, **kwargs):
            if args[0] == "send-keys" and "-l" in args:
                self.pane = self.fixture("prompt")    # typing replaces the suggestion
            return self.tmux(*args, **kwargs)

        with patch.object(orch, "tmux_out", side_effect=tmux):
            self.tick()
        self.assertEqual(self.typed, ["/rename lagoon"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_empty_composer_is_not_a_receipt_until_the_transcript_confirms(self):
        self.confirm_title = False
        orch.rename("lagoon", "quay")
        self.assertFalse(watch._holds_text(self.pane, "/rename quay"))
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.title("quay")
        self.tick()
        self.assertEqual(self.record()["session_title"], "quay")
        self.assertNotIn("title_sync", self.record())
        self.assertEqual(self.typed, ["/rename quay"])

    def test_one_name_is_typed_three_times_then_left_until_renamed(self):
        self.confirm_title = False
        orch.rename("lagoon", "quay", log=self.logs.append)
        for _ in range(6):
            self.tick()
        self.assertEqual(self.typed, ["/rename quay"] * 3)
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.assertEqual(sum("title did not take" in line for line in self.logs), 1)
        with patch.object(watch, "pane_text", wraps=watch.pane_text) as capture:
            watch.sync_title(self.seat, self.logs.append)
        capture.assert_not_called()
        before = list(self.commands)
        self.tick()
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[len(before):]))
        self.confirm_title = True
        orch.rename("quay", "harbor")
        self.assertEqual(self.typed, ["/rename quay"] * 3 + ["/rename harbor"])
        self.assertEqual(self.record()["session_title"], "harbor")

    def test_third_typing_gets_its_dropped_enter_on_the_next_tick(self):
        self.wrap_at = 10
        self.confirm_title = False
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.tick()
        self.drop_enter = True
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"] * 3)
        self.assertTrue(watch._holds_text(self.pane, "/rename quay"))
        before = len(self.commands)
        self.drop_enter = False
        self.confirm_title = True
        self.tick()
        self.assertEqual([args[-1] for args in self.commands[before:]
                          if args[0] == "send-keys"], ["Enter"])
        self.assertFalse(watch._holds_text(self.pane, "/rename quay"))
        self.assertEqual(self.typed, ["/rename quay"] * 3)
        self.assertEqual(self.record()["session_title"], "quay")

    def test_superseded_line_gets_enter_and_never_names_the_seat(self):
        self.wrap_at = 10
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        orch.rename("quay", "reed", log=self.logs.append)
        self.assertEqual(self.typed, ["/rename quay"])
        self.drop_enter = False
        before = len(self.commands)
        self.tick()
        self.assertEqual([args[-1] for args in self.commands[before:]
                          if args[0] == "send-keys"], ["Enter"])
        self.assertFalse(watch._holds_text(self.pane, "/rename quay"))
        self.tick()
        self.assertEqual(self.seat["name"], "reed")
        self.assertEqual(self.typed, ["/rename quay", "/rename reed"])
        self.assertEqual(self.record()["session_title"], "reed")
        self.assertEqual(claude.session_title(self.record()), "reed")
        self.title("quay")
        self.tick()
        self.assertEqual(self.seat["name"], "reed")
        self.assertEqual(claude.session_title(self.record()), "reed")

    def test_title_receipt_does_not_forget_a_line_still_in_the_composer(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.title("quay")
        self.tick()
        self.drop_enter = False
        before = len(self.commands)
        self.tick()
        self.assertEqual([args[-1] for args in self.commands[before:]
                          if args[0] == "send-keys"], ["Enter"])
        self.assertFalse(watch._holds_text(self.pane, "/rename quay"))
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_superseded_line_sent_later_by_the_owner_is_still_ours(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        orch.rename("quay", "reed", log=self.logs.append)
        self.drop_enter = False
        self.tmux("send-keys", "-t", "=reed:", "Enter")
        self.tick()
        self.assertEqual(self.seat["name"], "reed")
        self.assertEqual(self.typed, ["/rename quay", "/rename reed"])
        self.assertEqual(claude.session_title(self.record()), "reed")

    def test_owner_draft_replacing_a_superseded_line_is_untouched(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.pane = self.fixture("prompt").replace("❯\u00a0\n", "❯ /rename quay-side\n")
        pane = self.pane
        before = len(self.commands)
        orch.rename("quay", "reed", log=self.logs.append)
        self.title("quay")
        self.tick()
        self.assertEqual(self.seat["name"], "reed")
        self.assertEqual(self.pane, pane)
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))
        self.assertEqual(self.typed, ["/rename quay"])

    def test_owners_rename_draft_is_not_an_agentkit_line(self):
        self.pane = self.fixture("prompt").replace("❯\u00a0\n", "❯ /rename quay\n")
        pane = self.pane
        orch.rename("lagoon", "quay", log=self.logs.append)
        orch.rename("quay", "reed", log=self.logs.append)
        self.tick()
        self.assertEqual(self.pane, pane)
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands))
        self.assertEqual(self.typed, [])

    def test_sent_attempt_does_not_own_a_later_identical_draft(self):
        self.confirm_title = False
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.pane = self.fixture("prompt").replace("❯\u00a0\n", self.composer("/rename quay"))
        pane = self.pane
        before = len(self.commands)
        self.tick()
        orch.rename("quay", "reed", log=self.logs.append)
        self.tick()
        self.assertEqual(self.pane, pane)
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))

    def test_failed_attempt_does_not_own_a_later_identical_draft(self):
        self.confirm_title = False
        orch.rename("lagoon", "quay", log=self.logs.append)
        for _ in range(3):
            self.tick()
        self.pane = self.fixture("prompt").replace("❯\u00a0\n", self.composer("/rename quay"))
        pane = self.pane
        before = len(self.commands)
        self.tick()
        orch.rename("quay", "reed", log=self.logs.append)
        self.tick()
        self.assertEqual(self.pane, pane)
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))

    def test_clear_retires_pending_lines_and_superseded_titles(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        orch.rename("quay", "reed", log=self.logs.append)
        config.update_session("reed", conversation="next-conversation")
        self.transcript = self.transcript.with_name("next-conversation.jsonl")
        self.transcript.touch()
        pane = self.pane    # the owner has typed the same draft in the new conversation
        before = len(self.commands)
        self.tick()
        self.assertEqual(self.pane, pane)
        self.assertFalse(any(args[0] == "send-keys" for args in self.commands[before:]))
        self.pane = self.fixture("prompt")
        self.title("quay")
        self.tick()
        self.assertEqual(self.seat["name"], "quay")
        self.assertNotIn("title_superseded", self.record())

    def test_explicitly_retaking_a_name_retires_its_superseded_title(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        orch.rename("quay", "reed", log=self.logs.append)
        self.drop_enter = False
        self.tick()
        self.tick()
        orch.rename("reed", "quay", log=self.logs.append)
        orch.rename("quay", "cedar", log=self.logs.append)
        self.title("quay")
        self.tick()
        self.assertEqual(self.seat["name"], "quay")
        self.assertNotIn("title_superseded", self.record())

    def test_old_empty_title_cache_cannot_confirm_a_rename(self):
        self.assertEqual(claude.session_title(self.record()), "")
        cache = config.STATE / "title-lagoon.json"
        cached = json.loads(cache.read_text())
        cached.pop("readable")
        cached["title"] = None
        cache.write_text(json.dumps(cached))
        self.confirm_title = False
        orch.rename("lagoon", "quay")
        self.tick()
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.title("quay")
        self.tick()
        self.assertEqual(self.record()["session_title"], "quay")

    def test_invalid_utf8_transcript_still_uses_the_composer_when_cached(self):
        self.transcript.write_bytes(b"\xff")
        self.pane = self.fixture("working")
        self.drop_enter = True
        self.confirm_title = False
        orch.rename("lagoon", "quay", log=self.logs.append)
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.drop_enter = False
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_a_line_left_in_the_composer_is_never_typed_again(self):
        self.drop_enter = True
        orch.rename("lagoon", "quay", log=self.logs.append)
        for _ in range(5):
            self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "lagoon")

    def test_unreadable_transcript_uses_composer_even_mid_turn(self):
        self.pane = self.fixture("working")
        self.drop_enter = True
        original = Path.open

        def unreadable(path, *args, **kwargs):
            if path == self.transcript:
                raise PermissionError("fake unreadable transcript")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", unreadable):
            orch.rename("lagoon", "quay", log=self.logs.append)
            self.assertEqual(self.record()["session_title"], "lagoon")
            self.drop_enter = False
            self.confirm_title = False
            self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_seat_lock_covers_key_gap_but_not_send_waits(self):
        self.drop_enter = True
        pauses = []

        def sleep(seconds):
            with config.notify_path(self.seat["name"]).with_suffix(".lock").open("a") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    locked = True
                else:
                    locked = False
                    fcntl.flock(handle, fcntl.LOCK_UN)
            pauses.append((seconds, locked))

        with patch.object(watch.time, "sleep", side_effect=sleep):
            orch.rename("lagoon", "quay", log=self.logs.append)
        self.assertEqual(pauses, [(watch.KEY_GAP, True), (watch.SENT_POLL, False),
                                  (watch.SENT_POLL, False)])

    def test_cli_and_menu_keep_send_warnings(self):
        self.fail_send = True
        with redirect_stdout(io.StringIO()) as output:
            orch.cmd_rename(["lagoon", "quay"])
        self.assertIn("WARN could not type into the quay seat", output.getvalue())
        with patch.dict(os.environ, {config.SESSION_ENV: "quay"}), \
                patch.object(orch, "ask_name", return_value="harbor"), \
                redirect_stdout(io.StringIO()) as output:
            menu.rename_this_session(False)
        self.assertIn("WARN could not type into the harbor seat", output.getvalue())


if __name__ == "__main__":
    unittest.main()
