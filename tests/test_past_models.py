"""A past session's row names the models it used: its orchestrator, then every other its runs
ran on, once each and by name.

The owner (20 Oct 2026) named the stats a past session opens with: "number of tasks, how long it
took ... and which models where used".  A run's history row holds the pair it ended with, so a
builder its turn went from is read off its record, and a reviewer off its reviews, by the name the
config runs it under, else its own.  Offline: a temporary HOME and its history database.
"""

from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, menu, terminal


class PastModels(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "acme-docs", "spark", ["opus"], {"cwd": "/", "created": 1000})
        # the name it was born with leads to it, as a rename leaves it
        config.session_path("acme-old").write_text('{"renamed": "acme-docs"}')
        for run, session, models, at in (("1", "acme-old", ("spark", "opus", None), 2000),
                                          ("2", "acme-docs", ("spark", "spark", "astra"), 3000),
                                          ("3", "acme-docs", ("grok", "grok", "grok"), 50000)):
            history._write(lambda connection, row=(run, session, *models, at): connection.execute(
                "INSERT INTO runs (run_id, session, orchestrator, executor, reviewer, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?)", row))
        # fable built run 2 before spark took over: its history row names spark alone
        (config.RUNS / "2").mkdir()
        (config.RUNS / "2" / "run.json").write_text(
            '{"executor_history": [{"from": "fable", "to": "spark", "reason": "stalled"}]}')
        for review, (harness, model, effort) in enumerate((
                ("antigravity", "gemini-3.8-flash", "high"), ("codex", "gpt-6-astra", "xhigh")), 1):
            history.record_review("2", f"review-{review}", harness=harness, model=model, blocking=0,
                                  followup=0, note=0, round=review, verdict="PASS", effort=effort)
        self.session = {"name": "acme-docs", "created": 1000, "closed": 40000}

    def test_its_orchestrator_then_every_model_its_runs_used_once_each_by_name(self):
        # grok's run began after the stop, and is not this session's
        self.assertEqual(menu.past_models(self.cfg, self.session),
                         ["spark", "astra", "fable", "gemini", "opus"])

    def test_a_reviewer_no_longer_configured_keeps_its_own_name(self):
        config.remove_model(self.cfg, "gemini")
        self.assertEqual(menu.past_models(self.cfg, self.session),
                         ["spark", "astra", "fable", "gemini-3.8-flash", "opus"])

    def test_they_close_the_stats_line_by_their_full_names(self):
        with patch.object(menu.notify, "conversation_of", return_value=None):
            self.assertEqual(menu.past_said(self.cfg, self.session)[1],
                             "took 11 hours · muse-spark-1.3-contributor, GPT-6-Astra, Fable 5.1,"
                             " Gemini 3.8 Flash, Opus 5.5")

    def test_its_row_names_its_orchestrator_in_full_and_whole_where_there_is_room(self):
        out = io.StringIO()
        with redirect_stdout(out), patch.object(menu, "past_said", return_value=("", "")), \
                patch.object(terminal, "width", return_value=100):
            menu.show_past(self.cfg, [{**self.session, "repo": None, "path": "/"}], dry_run=True)
        self.assertIn("1 acme-docs muse-spark-1.3-contributor stopped",
                      terminal.plain(out.getvalue()))

    def test_a_name_stays_on_one_line_where_the_stats_wrap(self):
        stats = "2 of 3 tasks · took 7 hours · muse-spark-1.3-contributor, GPT-6-Astra, Gemini 3.8 Flash"
        self.assertEqual(menu.stats_lines(stats, 34), [
            "2 of 3 tasks · took 7 hours ·", "muse-spark-1.3-contributor,",
            "GPT-6-Astra, Gemini 3.8 Flash"])
        self.assertEqual(menu.stats_lines(stats, 200), [stats])
        self.assertEqual(menu.stats_lines("took 7 hours · muse-spark-1.3-contributor", 12),
                         ["took 7 hours", "·", "muse-spark-1", ".3-contribut", "or"])


if __name__ == "__main__":
    unittest.main()
