"""Seat renames reach Claude safely and once; fake tmux and panes, a temporary HOME."""

from contextlib import redirect_stdout
import io
import os
import shlex
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, notify, orch, watch


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
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        # Keep the health pass's unrelated recovery and notification work offline.
        for method in ("poll_worker_token", "seat_account", "stop_nudge", "announce_state"):
            self.stack.enter_context(patch.object(watch, method, return_value=False))
        config.save_session(self.cfg, "lagoon", "opus", ["opus"], {
            "cwd": str(self.root), "session_title": "lagoon"})

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
        return 0, ""

    def record(self):
        return config.session_records()[self.seat["name"]]

    def tick(self, dry=False):
        state = watch.load_state()
        watch.health(self.cfg, state, dry, lambda _: None)
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

    def test_resume_records_the_name_passed_to_remote_control(self):
        config.update_session("lagoon", conversation="fake-conversation", id_source=orch.LAUNCHER,
                              session_title="former-name")
        self.seat["exited"] = True
        with patch.object(orch, "opened", return_value=True):
            self.assertEqual(orch.resume(self.cfg, "lagoon", log=lambda _: None,
                                         hand_over=False), "resumed")
        words = shlex.split(next(args[-1] for args in self.commands if args[0] == "respawn-pane"))
        self.assertEqual(words[words.index("--remote-control") + 1], "lagoon")
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.seat["exited"] = False
        self.tick()
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
        orch.rename("lagoon", "quay")
        self.assertEqual(self.typed, [])
        self.assertEqual(self.record()["session_title"], "lagoon")
        self.fail_send = False
        self.tick()
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(self.record()["session_title"], "quay")

    def test_dropped_enter_retries_only_the_enter(self):
        enters = []

        def tmux(*args, **kwargs):
            answer = self.tmux(*args, **kwargs)
            if args[0] == "send-keys":
                if "-l" in args:
                    self.pane = f"❯ {args[-1]}"
                elif args[-1] == "Enter":
                    enters.append(True)
                    if len(enters) == 2:
                        self.pane = self.fixture("prompt")
            return answer

        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "SENT_WAIT", watch.SENT_POLL), \
                patch.object(watch.time, "sleep"):
            orch.rename("lagoon", "quay")
        self.assertEqual(self.typed, ["/rename quay"])
        self.assertEqual(len(enters), 2)
        self.assertEqual(self.record()["session_title"], "quay")


if __name__ == "__main__":
    unittest.main()
