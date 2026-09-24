"""v5v: the interactive new-session picker after project selection was removed."""

from contextlib import redirect_stdout
import io
from pathlib import Path
from unittest.mock import patch
import unittest

from test_new_session import NewSession
from agentkit import config, menu, orch, terminal, usage


class Picker(NewSession):
    def test_screen_has_two_spaced_blocks_and_no_name(self):
        with self.answers(["", ""]), \
                patch.object(terminal, "width", return_value=100), \
                redirect_stdout(io.StringIO()) as out:
            menu.new_session(self.cfg, True)
        text = out.getvalue()
        self.assertIn("Orchestrator [opus]:", text)
        self.assertIn("Workers [opus astra]:", text)
        self.assertNotIn("Name [", text)
        self.assertNotIn("Project [", text)
        self.assertLess(text.index("Orchestrator"), text.index("Workers"))

    def test_workers_typo_repeats_the_same_prompt(self):
        with self.answers(["", "z", "all"]), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.new_session(self.cfg, True), "opus")
        self.assertIn("not a choice: 'z'", out.getvalue())
        self.assertGreaterEqual(out.getvalue().count("Workers [opus astra]:"), 2)

    def test_prompt_worker_choices_are_every_model_the_orchestrator_included(self):
        self.assertEqual(self.new(["", "all"]), "opus")
        self.assertEqual(config.load_session(self.cfg, "opus")["workers"],
                         config.offered(self.cfg))
        self.assertIn("opus", config.load_session(self.cfg, "opus")["workers"])

    def test_orchestrator_reason_suffixes_keep_skips_and_warn(self):
        providers = {}
        def skipped(cfg, name, _providers):
            return (name != "astra", "session 100.0% used >= 100" if name != "astra"
                    else "weekly 10.0% used < 100")
        with patch.object(usage, "model_spent", side_effect=skipped):
            default, reason = orch.choose(self.cfg, providers)
        with self.answers([""]), redirect_stdout(io.StringIO()) as out, \
                patch.object(usage, "model_spent", side_effect=skipped):
            self.assertEqual(orch.prompt_orchestrator(self.cfg, default, providers, reason), "astra")
        # both skips follow the bracket, however the prompt wraps
        shown = " ".join(out.getvalue().split())
        self.assertIn("(skipped opus: session 100.0% used >= 100; "
                      "skipped fable: session 100.0% used >= 100)", shown)

        spent = lambda cfg, name, _providers: (True, "session 100.0% used >= 100")
        with patch.object(usage, "model_spent", side_effect=spent):
            default, reason = orch.choose(self.cfg, providers)
        with self.answers([""]), redirect_stdout(io.StringIO()) as out, \
                patch.object(usage, "model_spent", side_effect=spent):
            self.assertEqual(orch.prompt_orchestrator(self.cfg, default, providers, reason), default)
        self.assertIn("WARN", out.getvalue())
        self.assertIn(f"launching {default} anyway", out.getvalue())

    def test_worker_names_are_case_insensitive(self):
        self.assertEqual(self.new(["", "OPUS, FABLE"]), "opus")
        self.assertEqual(config.load_session(self.cfg, "opus")["workers"], ["opus", "fable"])

    def test_worker_number_order_is_preserved(self):
        self.assertEqual(self.new(["", "2 1"]), "opus")
        self.assertEqual(config.load_session(self.cfg, "opus")["workers"], ["opus", "fable"])

    def test_name_default_follows_orchestrator_and_taken_names(self):
        self.assertEqual(orch.default_name("fable", set()), "fable")
        self.assertEqual(orch.default_name("fable", {"fable"}), "fable-2")
        self.assertEqual(orch.default_name("fable", {"fable", "fable-2"}), "fable-3")

    def test_direct_orch_keeps_cwd_without_a_project_question(self):
        cwd = self.root / "outside"
        cwd.mkdir()
        with patch.object(orch, "maintenance"), patch.object(orch, "attach"), \
                patch.object(orch, "launch"), patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(Path, "cwd", return_value=cwd), self.answers(["", "all"]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["--dry-run"]), 0)
        record = config.load_session(self.cfg, "opus")
        self.assertEqual(record["cwd"], str(cwd))
        self.assertIsNone(record["repo"])

    def test_forced_workers_skip_the_picker(self):
        with patch.object(orch, "prompt_workers", side_effect=AssertionError("must skip")), \
                patch.object(orch, "prompt_orchestrator", side_effect=AssertionError("must skip")), \
                redirect_stdout(io.StringIO()):
            orch.main(["forced", "--model", "astra", "--workers", "opus", "--dry-run"])
        record = config.load_session(self.cfg, "forced")
        self.assertEqual((record["orchestrator"], record["workers"]), ("astra", ["opus"]))

    def test_model_flag_only_prompts_workers(self):
        with self.answers(["all"]), patch.object(orch, "prompt_workers", wraps=orch.prompt_workers) as ask, \
                redirect_stdout(io.StringIO()):
            orch.main(["model-only", "--model", "astra", "--dry-run"])
        ask.assert_called_once()
        record = config.load_session(self.cfg, "model-only")
        self.assertEqual(record["orchestrator"], "astra")
        self.assertEqual(record["workers"], config.offered(self.cfg))

    def test_q_at_first_and_last_questions_create_nothing(self):
        self.assertIsNone(self.new(["q"]))
        self.assertIsNone(self.new(["", "q"]))

        with self.answers(["q"]), patch.object(orch, "maintenance"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["--dry-run"]), 0)
        self.assertEqual(list(config.STATE.glob("session-*.json")), [])

    def test_empty_name_without_default_repeats(self):
        with self.answers(["", "chosen"]), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.ask_name(set(), None), "chosen")
        self.assertIn("a session needs a name", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
