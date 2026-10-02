"""A new seat asks its name first; only an unnamed seat asks its orchestrator to name it.

Offline, under a temporary HOME: model commands write the real rulebook, but no harness or
tmux session starts. The same records feed creation, resumption and both rename entry points.
"""

from contextlib import contextmanager, redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, menu, orch, terminal, usage, watch
from agentkit.harness import claude
from tools import rulebook

PROMPT = "Name (Enter: auto): "
RULE = "This seat is unnamed."


class SeatNameAsked(Sandbox):
    def setUp(self):
        super().setUp()
        self.rules = []
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(orch, "maintenance"))
        self.stack.enter_context(patch.object(orch, "launch"))
        self.stack.enter_context(patch.object(orch, "attach", return_value=0))
        self.stack.enter_context(patch.object(menu, "open_session"))
        self.stack.enter_context(patch.object(orch, "command", side_effect=self.command))

    def command(self, cfg, model, *args, **kwargs):
        self.rules.append(rulebook.write(config.current_session()).read_text())
        return ["fake"]

    def start(self, entry, answers):
        # Use the real line reader over a pipe-like stdin: EOF takes every remaining default.
        with patch.object(sys, "stdin", io.StringIO(answers)), redirect_stdout(io.StringIO()) as out:
            if entry == "menu":
                name = menu.new_session(self.cfg, False)
            else:
                self.assertEqual(orch.main([]), 0)
                name = orch.attach.call_args.args[0] if orch.attach.called else None
        return name, out.getvalue()

    def running(self, name):
        seat = {"name": name, "legacy": False}
        self.held = {name}

        def tmux(*args, **kwargs):
            if args[0] == "list-sessions":
                self.assertEqual(kwargs["socket"], orch.socket_name())
                return 0, "\n".join(sorted(self.held))
            if args[0] == "rename-session":
                self.assertEqual(args[2], f"={seat['name']}")
                if args[-1] in self.held:
                    return 1, f"duplicate session: {args[-1]}"
                self.held.remove(seat["name"])
                self.held.add(args[-1])
                seat["name"] = args[-1]
            return 0, ""

        self.stack.enter_context(patch.object(orch, "sessions", return_value=[seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=tmux))
        self.stack.enter_context(patch.object(watch, "announce_state"))
        self.stack.enter_context(patch.object(watch, "sync_title"))
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: name}))
        return seat

    def test_typed_name_is_normalized_before_models_are_chosen(self):
        for entry, typed in (("menu", "Fix / API.v2"), ("orch", "Acme / Parser")):
            with self.subTest(entry=entry):
                name, text = self.start(entry, typed + "\n\n\n")
                self.assertEqual(name, orch.session_name(typed))
                self.assertLess(text.index(PROMPT), text.index("Orchestrator ["))
                self.assertLess(text.index("Orchestrator ["), text.index("Workers ["))
                self.assertNotIn("unnamed", config.load_session(self.cfg, name))
                self.assertNotIn(RULE, self.rules[-1])

    def test_enter_creates_unique_placeholders_and_eof_also_means_auto(self):
        for entry, answers, expected in (("menu", "\n\n\n", "new"),
                                          ("orch", "\n\n\n", "new-2"),
                                          ("menu", "", "new-3"), ("orch", "", "new-4")):
            with self.subTest(entry=entry, answers=answers):
                name, text = self.start(entry, answers)
                self.assertEqual(name, expected)
                self.assertIn(PROMPT, text)
                self.assertTrue(config.load_session(self.cfg, name)["unnamed"])
                self.assertIn(RULE, self.rules[-1])
                self.assertIn("as the conversation tells you what the job is", self.rules[-1])
                self.assertIn("`ak orch rename --auto <name>`", self.rules[-1])
                self.assertIn("shortest possible name, at most three words", self.rules[-1])

    def test_taken_name_asks_again(self):
        self.start("menu", "Fix API\n\n\n")
        for entry in ("menu", "orch"):
            with self.subTest(entry=entry):
                chosen = f"{entry}-parser"
                name, text = self.start(entry, f"FIX/API\n{chosen}\n\n\n")
                self.assertEqual(name, chosen)
                self.assertEqual(text.count(PROMPT), 2)
                self.assertIn("a session named fix-api is already there", text)

    def test_esc_creates_nothing_and_never_asks_for_models(self):
        for entry in ("menu", "orch"):
            with self.subTest(entry=entry):
                name, text = self.start(entry, "\x1b\n")
                self.assertIsNone(name)
                self.assertNotIn("Orchestrator", text)
                self.assertEqual(config.session_records(), {})
                self.assertEqual(list(config.STATE.glob("rulebook-*.md")), [])
        usage.collect.assert_not_called()
        orch.launch.assert_not_called()
        menu.open_session.assert_not_called()

    def test_a_typed_placeholder_is_already_named(self):
        name, _ = self.start("menu", "new\n\n\n")
        self.assertEqual(name, "new")
        self.assertNotIn("unnamed", config.load_session(self.cfg, name))
        self.assertNotIn(RULE, self.rules[-1])
        seat = self.running(name)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["rename", "--auto", "parser"]), 0)
        self.assertIn("already named new", out.getvalue())
        self.assertEqual(seat["name"], "new")

    def test_resume_repeats_the_rule_only_until_a_rename(self):
        self.start("menu", "\n\n\n")
        with patch.object(orch, "opened", return_value=True):
            orch.resume(self.cfg, "new", log=lambda _: None, hand_over=False)
        self.assertIn(RULE, self.rules[-1])
        with patch.object(orch, "find", return_value={"name": "new"}), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "announce_state"):
            self.assertEqual(orch.rename("new", "fix-api"), "fix-api")
        with patch.object(orch, "opened", return_value=True):
            orch.resume(self.cfg, "fix-api", log=lambda _: None, hand_over=False)
        self.assertNotIn("unnamed", config.load_session(self.cfg, "fix-api"))
        self.assertNotIn(RULE, self.rules[-1])

    def test_cli_rename_clears_the_mark_even_when_keeping_the_name(self):
        for entry in ("orch",):
            for new in ("fix-api", "new"):
                with self.subTest(entry=entry, new=new):
                    # Each case has its own state so `new` is free again.
                    for path in config.STATE.glob("session-*.json"):
                        path.unlink()
                    self.start("menu", "\n\n\n")
                    with patch.dict(os.environ, {config.SESSION_ENV: "new"}), \
                            patch.object(orch, "find", return_value={"name": "new"}), \
                            patch.object(orch, "tmux_out", return_value=(0, "")), \
                            patch.object(watch, "announce_state"), \
                            patch.object(sys, "stdin", io.StringIO(new + "\n")), \
                            redirect_stdout(io.StringIO()):
                        self.assertEqual(orch.main(["rename", new]), 0)
                    self.assertNotIn("unnamed", config.load_session(self.cfg, new))
                    self.assertNotIn(RULE, rulebook.write(new).read_text())

    def test_auto_gives_an_unnamed_seat_only_its_first_name(self):
        self.start("menu", "\n\n\n")
        seat = self.running("new")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["rename", "--auto", "fix-api"]), 0)
        self.assertEqual(seat["name"], "fix-api")
        self.assertNotIn("unnamed", config.load_session(self.cfg, "new"))
        before = config.session_path("fix-api").read_bytes()
        orch.tmux_out.reset_mock()
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["rename", "--auto", "new", "parser"]), 0)
        self.assertIn("already named fix-api", out.getvalue())
        self.assertEqual(config.session_path("fix-api").read_bytes(), before)
        orch.tmux_out.assert_not_called()

    def test_auto_keeps_an_owner_name_but_a_plain_rename_can_change_it(self):
        for entry in ("orch",):
            with self.subTest(entry=entry):
                for path in config.STATE.glob("session-*.json"):
                    path.unlink()
                self.start("menu", "\n\n\n")
                seat = self.running("new")
                with patch.object(sys, "stdin", io.StringIO("fix-api\n")), \
                        redirect_stdout(io.StringIO()):
                    self.assertEqual(orch.main(["rename", "fix-api"]), 0)
                # The running conversation still carries the placeholder in its environment.
                os.environ[config.SESSION_ENV] = "new"
                before = config.session_path("fix-api").read_bytes()
                orch.tmux_out.reset_mock()
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(orch.main(["rename", "--auto", "parser"]), 0)
                self.assertIn("already named fix-api", out.getvalue())
                self.assertEqual(seat["name"], "fix-api")
                self.assertEqual(config.session_path("fix-api").read_bytes(), before)
                orch.tmux_out.assert_not_called()
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(orch.main(["rename", "parser"]), 0)
                self.assertEqual(seat["name"], "parser")

    def test_auto_rechecks_the_name_after_waiting_for_the_lock(self):
        self.start("menu", "\n\n\n")
        seat = self.running("new")
        lock = watch.state_lock

        @contextmanager
        def owner_first():
            with lock():
                config.rename_session("new", "fix-api")
                config.update_session("fix-api", unnamed=None)
                seat["name"] = "fix-api"
                yield

        with patch.object(watch, "state_lock", owner_first), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["rename", "--auto", "parser"]), 0)
        self.assertIn("already named fix-api", out.getvalue())
        self.assertEqual(seat["name"], "fix-api")
        orch.tmux_out.assert_not_called()

    def test_cli_and_menu_can_take_back_the_seats_own_name(self):
        for entry in ("orch",):
            with self.subTest(entry=entry):
                for path in config.STATE.glob("session-*.json"):
                    path.unlink()
                orch.sessions.return_value = []
                self.held = set()
                self.start("menu", "foo\n\n\n")
                seat = self.running("foo")
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(orch.main(["rename", "bar"]), 0)
                    self.assertEqual(orch.main(["rename", "foo"]), 0)
                self.assertEqual(seat["name"], "foo")
                self.assertEqual(set(config.session_records()), {"foo"})
                self.assertEqual(config.resolve_session("foo"), "foo")
                self.assertEqual(config.resolve_session("bar"), "foo")

    def test_cli_refuses_its_former_name_when_tmux_holds_it(self):
        self.start("menu", "foo\n\n\n")
        seat = self.running("foo")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["rename", "bar"]), 0)
        self.held.add("foo")
        before = config.session_records()
        orch.tmux_out.reset_mock()
        with self.assertRaisesRegex(config.Error, "^the name 'foo' is already spoken for$"):
            orch.main(["rename", "foo"])
        self.assertEqual(seat["name"], "bar")
        self.assertEqual(config.session_records(), before)
        self.assertEqual(config.resolve_session("foo"), "bar")
        self.assertFalse(any(call.args[0] == "rename-session"
                             for call in orch.tmux_out.call_args_list))

    def test_claude_title_gets_a_stable_variant_when_tmux_holds_its_former_name(self):
        self.start("menu", "foo\n\n\n")
        seat = self.running("foo")
        self.assertEqual(orch.rename("foo", "bar"), "bar")
        self.held.add("foo")
        record = config.update_session("bar", cwd=str(self.root), conversation="fake-conversation",
                                       session_title="bar")
        transcript = claude.transcript_path(record, "fake-conversation")
        transcript.parent.mkdir(parents=True)
        transcript.write_text('{"type":"custom-title","customTitle":"foo",'
                              '"sessionId":"fake-conversation"}\n')
        with patch.object(orch, "rename", wraps=orch.rename) as rename:
            self.assertEqual(watch.follow_title(seat), "foo-2")
            self.assertEqual(seat["name"], "foo-2")
            self.assertEqual(config.resolve_session("foo"), "foo-2")
            self.assertIsNone(watch.follow_title(seat))
        rename.assert_called_once()
        self.assertEqual(self.held, {"foo", "foo-2"})

    def test_bad_argument_usage_includes_auto_rename(self):
        with self.assertRaisesRegex(config.Error, r"ak orch rename \[--auto\] \[OLD\] NEW"):
            orch.parse(["--unknown"])

    def test_config_can_reclaim_a_name_through_a_chain_without_a_loop(self):
        self.start("menu", "foo\n\n\n")
        before = config.load_session(self.cfg, "foo")
        for old, new in (("foo", "bar"), ("bar", "quay"), ("quay", "foo")):
            config.rename_session(old, new)
        for name in ("foo", "bar", "quay"):
            self.assertEqual(config.resolve_session(name), "foo")
            self.assertEqual(config.load_session(self.cfg, name), before)

    def test_legacy_seat_can_reclaim_its_name_without_a_record_or_loop(self):
        seat = self.running("foo")
        seat["legacy"] = True
        self.assertEqual(orch.rename("foo", "bar"), "bar")
        self.assertEqual(orch.rename("bar", "foo"), "foo")
        self.assertEqual(seat["name"], "foo")
        self.assertEqual(config.resolve_session("foo"), "foo")
        self.assertEqual(config.resolve_session("bar"), "foo")
        self.assertEqual(config.session_records(), {})

    def test_another_seats_former_name_is_still_reserved(self):
        self.start("menu", "foo\n\n\n")
        config.rename_session("foo", "bar")
        self.start("menu", "quay\n\n\n")
        seat = self.running("quay")
        before = config.session_records()
        with self.assertRaisesRegex(config.Error, "already spoken for"):
            orch.main(["rename", "foo"])
        with self.assertRaisesRegex(config.Error, "points at another session"):
            config.rename_session("quay", "foo")
        self.assertEqual(seat["name"], "quay")
        self.assertEqual(config.session_records(), before)
        self.assertEqual(config.resolve_session("foo"), "bar")

    def test_named_cli_and_ensure_still_skip_the_name_question(self):
        self.start("menu", "\n\n\n")
        self.rules.clear()
        with patch.object(terminal, "readline", side_effect=AssertionError("unexpected question")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["new", "--model", "opus", "--workers", "astra"]), 0)
            self.assertTrue(orch.ensure(self.cfg, "acme", log=lambda _: None))
        for name in ("new", "acme"):
            self.assertNotIn("unnamed", config.load_session(self.cfg, name))
        self.assertTrue(all(RULE not in body for body in self.rules))

    def test_failed_command_leaves_no_placeholder_record(self):
        with patch.object(orch, "command", side_effect=config.Error("adapter failed")):
            with self.assertRaisesRegex(config.Error, "adapter failed"):
                self.start("menu", "\n\n\n")
        self.assertEqual(config.session_records(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
