"""`usage.held`: what `collect` answers from the snapshot, however old, with no adapter asked.

The screens that must be up at once read it (a seat's `c`, and `a`): a window past its reset is
gone from it, each account's too, so a week that rolled over neither refuses a move nor dims a
row; a provider the config no longer has is left out; with no snapshot it is empty.  Offline,
in a temporary HOME (tests/fixtures/sandbox.py) whose clock reads 10000.
"""

import json
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, usage

NOW = 10000


def meter(used, resets_at):
    return {"name": "weekly_all", "used": used, "resets_at": resets_at, "window_secs": 604800}


class Held(Sandbox):
    def setUp(self):
        super().setUp()
        for asked in ("_probe", "_adapter_json"):
            self.stack.enter_context(patch.object(usage, asked, side_effect=AssertionError(asked)))
        self.cfg["providers"]["acme"] = {"mode": "subscription", "accounts": ["work", "home"]}

    def hold(self, **providers):
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 0,
                                                             "providers": providers}))

    def test_a_window_past_its_reset_is_gone_each_account_s_too(self):
        self.hold(acme={"meters": [meter(100, NOW - 1)], "accounts": {
            "work": {"meters": [meter(100, NOW - 1)]},
            "home": {"meters": [meter(40, NOW + 86400)]}}})
        held = usage.held(self.cfg)["acme"]
        self.assertEqual([m["used"] for m in held["accounts"]["work"]["meters"]], [])
        self.assertEqual([m["used"] for m in held["accounts"]["home"]["meters"]], [40])
        self.assertFalse(held["exhausted"])

    def test_a_provider_the_config_no_longer_has_is_left_out(self):
        self.hold(gone={"meters": [meter(40, NOW + 86400)]})
        self.assertEqual(usage.held(self.cfg), {})

    def test_nothing_held_is_nothing(self):
        self.assertEqual(usage.held(self.cfg), {})


if __name__ == "__main__":
    unittest.main()
