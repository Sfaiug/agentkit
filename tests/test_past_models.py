"""A past session's row names the models it used: its orchestrator, then every other its runs
ran on, once each and by name.

The owner (20 Oct 2026) named the stats a past session opens with: "number of tasks, how long it
took ... and which models where used".  A run's history row holds the pair it ended with, so a
builder its turn went from is read off its record, and a reviewer off its reviews, by the name the
config runs it under, else its own.  Offline: a temporary HOME and its history database.
"""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, menu


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

    def test_they_close_the_stats_line(self):
        with patch.object(menu.notify, "conversation_of", return_value=None):
            self.assertEqual(menu.past_said(self.cfg, self.session)[1],
                             "took 11 hours · spark, astra, fable, gemini, opus")


if __name__ == "__main__":
    unittest.main()
