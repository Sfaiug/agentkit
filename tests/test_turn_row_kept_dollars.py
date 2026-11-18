"""A turn's `turn_usage` row keeps what it cost at listed prices (`history._listed_usd`) only as a
cost a float holds, and keeps it while its counts do.

- A turn counted after a later turn of its session takes its share back from that turn's rows:
  a row whose counts change is priced anew, one whose counts stay keeps its dollars, though the
  boards dropped its model since.
- A cost no float holds, as a price near a float's largest times millions of tokens or an
  integer price past it, which json reads whole, is none: the row keeps no dollars, and is
  priced as the boards list its model when it is read, where that cost is none too, so the
  login's listed spend is none, not infinite or NaN.

In-process on tests/fixtures/sandbox.py's HOME, each turn a Claude `result` in its events.
"""

from contextlib import closing
import json
import os
import sqlite3
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, history, spend


class KeptDollars(Sandbox):
    def board(self, model, price):
        """A board listing `model` alone, at `price` a million input tokens and $1 the rest."""
        row = {"model": model, "effort": None, "maker": "Acme", "deprecated": False,
               "slug": model, "release": {"slug": model, "name": model, "deprecatedTo": None},
               "values": {"aa.price1mInputTokens": price, "aa.cacheWritePrice": 1,
                          "aa.cacheHitPrice": 1, "aa.price1mOutputTokens": 1}}
        (config.STATE / "boards.json").write_text(json.dumps({"artificialanalysis.ai": {
            "rows": [row]}}))

    def turn(self, name, began, models):
        """Count a turn of one session that began at `began`, its input tokens by model."""
        out = config.RUNS / "fix-api" / "round-1" / name
        out.mkdir(parents=True)
        (out / "harness").write_text("claude")
        (out / "account").write_text(config.DEFAULT_ACCOUNT)
        os.utime(out / "harness", (began, began))
        (out / "events.jsonl").write_text(json.dumps({
            "type": "result", "subtype": "success", "session_id": "session-acme",
            "usage": {"input_tokens": sum(models.values())},
            "modelUsage": {model: {"inputTokens": tokens} for model, tokens in models.items()}}))
        os.utime(out / "events.jsonl", (began + 10, began + 10))
        history.add_turn_tokens("fix-api", "executor", [out], harness="claude")
        return str(out.resolve())

    def kept(self, turn):
        with closing(sqlite3.connect(history.path())) as db:
            return {model: (tokens, dollars) for model, tokens, dollars in db.execute(
                "SELECT model, input, listed_usd FROM turn_usage WHERE turn = ?", (turn,))}

    def setUp(self):
        super().setUp()
        history.start_run("fix-api")

    def test_a_row_whose_counts_stay_keeps_its_dollars_when_an_earlier_turn_counts_late(self):
        self.board("easel-2", 4)
        later = self.turn("executor-2", 200, {"anvil-1": 2_000_000, "easel-2": 3_000_000})
        self.board("anvil-1", 2)    # Easel 2's maker shipped the next one
        earlier = self.turn("executor-1", 100, {"anvil-1": 1_000_000})
        self.assertEqual(self.kept(earlier), {"anvil-1": (1_000_000, 2.0)})
        self.assertEqual(self.kept(later), {"anvil-1": (1_000_000, 2.0),
                                            "easel-2": (3_000_000, 12.0)})

    def test_a_cost_no_float_holds_keeps_no_dollars(self):
        self.costs_none(1e308)

    def test_an_integer_price_no_float_holds_keeps_no_dollars(self):
        self.costs_none(10**400)

    def costs_none(self, price):
        """A turn on a board listing `price` keeps no dollars, and its login's spend is none."""
        self.board("anvil-1", price)
        turn = self.turn("executor-1", 100, {"anvil-1": 2_000_000})
        self.assertEqual(self.kept(turn), {"anvil-1": (2_000_000, None)})
        self.assertIsNone(spend.listed(self.cfg, "anthropic", None, 0, 200))


if __name__ == "__main__":
    unittest.main()
