"""Spend reads a turn row's kept dollars (`listed_usd`) in the snapshot it reads the row in.

A history.db from before `listed_usd` gains it at its next write.  Where that write lands while
spend reads, with a row keeping its dollars, and the boards then drop the row's model, spend
sums the rows from before the write, or the new one too at its kept dollars: never the new row
priced as the rows it was read with, as a look at the columns before the write left it.

In-process on tests/fixtures/sandbox.py's HOME, each turn a Claude `result` in its events.
"""

from contextlib import closing
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, spend

CFG = {"models": {"acme": {"harness": "claude", "provider": "anthropic"}},
       "providers": {"anthropic": {}}}


class KeptDollarsReadWithTheirRow(Sandbox):
    def board(self, *models):
        """Boards listing each (model, price a million input tokens) of `models`, output $1."""
        (config.STATE / "boards.json").write_text(json.dumps({"artificialanalysis.ai": {"rows": [
            {"model": model, "effort": None, "maker": "Acme", "deprecated": False,
             "slug": model, "release": {"slug": model, "name": model, "deprecatedTo": None},
             "values": {"aa.price1mInputTokens": price, "aa.price1mOutputTokens": 1}}
            for model, price in models]}}))

    def turn(self, name, began, model):
        """A turn of a million input tokens of `model`, from `began` for ten seconds."""
        out = config.RUNS / "fix-api" / "round-1" / name
        out.mkdir(parents=True)
        (out / "account").write_text("default")
        (out / "harness").write_text("claude")
        os.utime(out / "harness", (began, began))
        (out / "events.jsonl").write_text(json.dumps({
            "type": "result", "subtype": "success", "session_id": f"session-{name}",
            "usage": {"input_tokens": 1_000_000},
            "modelUsage": {model: {"inputTokens": 1_000_000}}}))
        os.utime(out / "events.jsonl", (began + 10, began + 10))
        return out

    def test_a_write_adding_kept_dollars_during_a_read_misprices_no_row(self):
        history.start_run("fix-api")
        old = self.turn("executor-1", 100, "anvil-1")
        later = self.turn("executor-2", 200, "easel-2")
        with closing(sqlite3.connect(history.path())) as db, db:    # turn_usage before listed_usd
            db.execute("DROP TABLE turn_usage")
            db.execute("CREATE TABLE turn_usage (turn TEXT, run_id TEXT, role TEXT, account TEXT, "
                       "model TEXT, began REAL, at REAL, input INTEGER, cache_write INTEGER, "
                       "cache_read INTEGER, output INTEGER)")
            db.execute("INSERT INTO turn_usage VALUES (?, 'fix-api', 'executor', 'default', "
                       "'anvil-1', 100, 110, 1000000, 0, 0, 0)", (str(old.resolve()),))
        self.board(("anvil-1", 4), ("easel-2", 8))
        connect, landed = history._connect, []
        test = self

        class Read:
            """A read connection before whose first turn_usage query the write lands, after
            which Easel 2's maker ships the next one."""
            def __init__(self, db):
                self.db = db

            def __getattr__(self, name):
                return getattr(self.db, name)

            def execute(self, query, *args):
                if "FROM turn_usage" in query and not landed:
                    landed.append(history.add_turn_tokens("fix-api", "executor", [later],
                                                          harness="claude"))
                    test.board(("anvil-1", 4))
                return self.db.execute(query, *args)

        def connecting(*, readonly=False):
            db = connect(readonly=readonly)
            return Read(db) if readonly else db

        with patch.object(history, "_connect", connecting):
            spent = spend.listed(CFG, "anthropic", None, 90, 220)
        self.assertTrue(landed)
        self.assertIn(spent, (4.0, 12.0))   # before the write, or Easel 2 at the $8 it kept


if __name__ == "__main__":
    unittest.main()
