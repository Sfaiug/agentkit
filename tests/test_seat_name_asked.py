"""A new seat asks its name first; only an unnamed seat asks its orchestrator to name it.

Offline, under a temporary HOME: model commands write the real rulebook, but no harness or
tmux session starts. The same records feed creation, resumption and both rename entry points.
"""

from contextlib import redirect_stdout
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
from tools import rulebook

PROMPT = "Name (Enter: auto): "
RULE = "This seat is unnamed."


class SeatNameAsked(Sandbox):
    def setUp(self):
        super().setUp()
        self.rules = []
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(orch, "held_names", return_value=set()))
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
                self.assertIn("`ak orch rename <name>`", self.rules[-1])
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

    def test_q_creates_nothing_and_never_asks_for_models(self):
        for entry in ("menu", "orch"):
            with self.subTest(entry=entry):
                name, text = self.start(entry, "q\n")
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

    def test_cli_and_menu_rename_clear_the_mark_even_when_keeping_the_name(self):
        for entry in ("orch", "menu"):
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
                        if entry == "orch":
                            self.assertEqual(orch.main(["rename", new]), 0)
                        else:
                            menu.rename_this_session(False)
                    self.assertNotIn("unnamed", config.load_session(self.cfg, new))
                    self.assertNotIn(RULE, rulebook.write(new).read_text())

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
