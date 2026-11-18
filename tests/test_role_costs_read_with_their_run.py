"""Role costs (`spend.roles`) read a run that ended and its turn rows in one snapshot.

A run that ended resumes and keeps a new turn's row.  Where that lands while role costs read,
the run's sample is what it cost when it ended, or none, as it runs again: never the ended run
with the new turn's dollars in it.

In-process on tests/fixtures/sandbox.py's HOME, each turn a Claude `result` in its events.
"""

import json
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, spend, staffing, usage

CFG = {"models": {"acme": {"harness": "claude", "provider": "anthropic"}},
       "providers": {"anthropic": {}}}


class RoleCostsReadWithTheirRun(Sandbox):
    def turn(self, number, began, tokens):
        """A kept executor turn of `tokens` input tokens, from `began` for ten seconds."""
        out = config.RUNS / "fix-api" / "round-1" / f"executor-{number}"
        out.mkdir(parents=True)
        (out / "account").write_text("default")
        (out / "harness").write_text("claude")
        os.utime(out / "harness", (began, began))
        (out / "events.jsonl").write_text(json.dumps({
            "type": "result", "subtype": "success", "session_id": f"session-{number}",
            "usage": {"input_tokens": tokens}, "modelUsage": {"anvil-1": {"inputTokens": tokens}}}))
        os.utime(out / "events.jsonl", (began + 10, began + 10))
        history.add_turn_tokens("fix-api", "executor", [out], harness="claude")

    def test_a_resume_during_a_read_adds_no_new_turn_to_the_ended_sample(self):
        # $4 a million input tokens, a week of $100: a million tokens cost $4, 4 points
        for one in (patch.object(spend, "_pricing", return_value=lambda model: (4, 4, 4, 1)),
                    patch.object(staffing, "_cached_providers", return_value={"anthropic": {}}),
                    patch.object(usage, "plan_weeks",
                                 return_value={"anthropic": {"default": ("team", 100)}}),
                    patch.object(usage, "price", return_value=20),
                    patch.object(config, "lists", return_value=True)):
            one.start()
            self.addCleanup(one.stop)
        history.start_run("fix-api", executor="acme", kind="task")
        history._write(lambda db: db.execute(
            "UPDATE runs SET executor_effort = 'high' WHERE run_id = 'fix-api'"))
        self.turn(1, 100, 1_000_000)
        history.finish_run("fix-api", finished_at=150)
        connect, landed = history._connect, []
        test = self

        class Rows:
            """A read's rows, after whose first fetch from `runs` the run resumes and keeps a
            turn of two million tokens."""
            def __init__(self, cursor, ran):
                self.cursor, self.ran = cursor, ran

            def __getattr__(self, name):
                return getattr(self.cursor, name)

            def fetchall(self):
                rows = self.cursor.fetchall()
                if self.ran and not landed:
                    landed.append(history.start_run("fix-api", executor="acme", kind="task"))
                    test.turn(2, 200, 2_000_000)
                return rows

        class Read:
            def __init__(self, db):
                self.db = db

            def __getattr__(self, name):
                return getattr(self.db, name)

            def execute(self, query, *args):
                return Rows(self.db.execute(query, *args), "FROM runs" in query)

        def connecting(*, readonly=False):
            db = connect(readonly=readonly)
            return Read(db) if readonly else db

        with patch.object(history, "_connect", connecting):
            during = spend.roles(CFG)[1].get("acme", {}).get("high", {}).get("executor")
        self.assertTrue(landed)
        self.assertIsNone(spend.roles(CFG)[1].get("acme"))     # it runs again: no sample
        self.assertIn(during, ((4.0, 1, 4.0), None))


if __name__ == "__main__":
    unittest.main()
