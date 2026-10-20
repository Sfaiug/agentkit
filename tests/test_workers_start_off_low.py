"""A worker turn, and a seat that opens or moves, starts on a subscription not running low: one
begun with a few percent of a 5h window left was cut off while another had room."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_seat_account as base
from agentkit import config, orch, usage


class StartsOffLow(unittest.TestCase):
    setUp, tmux, type_into, meters = (base.SeatAccount.setUp, base.SeatAccount.tmux,
                                      base.SeatAccount.type_into, base.SeatAccount.meters)

    def picks(self, first, second, gone=2, scoped=0):
        """(a worker turn's account, the order a seat opens or moves in), each subscription's 5h
        window `first` or `second`% used `gone` hours in, the second's Fable week `scoped`%."""
        def reading(used, scoped=0):
            meters = ({"name": "session", "used": used, "window_secs": usage.SESSION_SECS,
                       "resets_at": self.now + usage.SESSION_SECS - gone * 3600},
                      {"name": "weekly_scoped", "used": scoped, "window_secs": 604800,
                       "resets_at": self.now + 3 * 86400})
            return {"provider": "anthropic",
                    "meters": [usage._normalized(meter, self.now) for meter in meters]}
        accounts = {"default": reading(first), "second": reading(second, scoped)}
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": self.now, "providers": {
            "anthropic": {**accounts["default"], "accounts": accounts}}}))
        readings = usage.collect(self.cfg)["anthropic"]["accounts"]
        return (usage.account(self.cfg, "anthropic", model="opus")[0],
                orch.account_order(self.cfg, "opus", readings))

    def test_a_subscription_running_low_is_taken_after_every_one_that_is_not(self):
        # 90% in two hours: the quarter hour until the next reading eats the rest
        self.assertEqual(self.picks(90, 10), ("second", ["second", "default"]))
        self.assertEqual(self.picks(90, 10, gone=4.5), ("second", ["default", "second"]))
        self.assertEqual(self.picks(10, 97), ("default", ["default", "second"]))
        # Fable's own week running low on the spare is not Opus's
        self.assertEqual(self.picks(10, 10, scoped=97), ("second", ["default", "second"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
