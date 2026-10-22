"""A spent seat offers going on only with another provider; offline, with cached readings."""

import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, menu, staffing, terminal, usage


class GoOnOtherProvider(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.cfg = {
            "defaults": {"orchestrator": "acme-big", "workers": ["zeta"]},
            "models": {
                name: {"harness": "codex", "model": name, "effort": "high",
                       "provider": provider, "meter": meter}
                for name, provider, meter in (("acme-big", "acme", "big"),
                                              ("acme-small", "acme", "small"),
                                              ("zeta", "zed", "weekly"))},
            "providers": {"acme": {"mode": "subscription"}, "zed": {"mode": "subscription"}}}
        self.back = time.mktime(time.localtime(10000)[:3] + (19, 59, 0, 0, 0, -1))
        config.save_session(self.cfg, "acme-api", "acme-big", ["zeta"])
        self.stack.enter_context(patch.object(config, "harness_present", return_value=True))
        self.stack.enter_context(patch.object(menu, "seat_row_state", return_value={
            "word": "out of usage", "reason": "acme out of usage", "since": None,
            "resumes_at": self.back}))

    def cache(self, zeta_used):
        def meter(name, used):
            return {"name": name, "used": used, "resets_at": self.back,
                    "window_secs": 604800, "exhausted": used == 100,
                    "tier_a_exhausted": used == 100}

        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "acme": {"meters": [meter("big", 100), meter("small", 20)]},
            "zed": {"meters": [meter("weekly", zeta_used)]}}}))
        return menu.v5o_seat_info(self.cfg, 1, {"name": "acme-api"}, [], {}, {}, 10000)

    def test_room_on_the_same_provider_leaves_only_the_reset_sentence(self):
        info = self.cache(100)
        providers = staffing._cached_providers()
        self.assertTrue(usage.model_spent(self.cfg, "acme-big", providers)[0])
        self.assertFalse(usage.model_spent(self.cfg, "acme-small", providers)[0])
        self.assertIsNone(info["go_on"])
        self.assertEqual(menu.detail(self.cfg, info, 80), ["Acme has no usage left until 19:59."])
        for width in (80, 40, 12):
            with self.subTest(width=width):
                self.assertEqual(menu.choice_lines(info, width), [])
                self.assertEqual(menu.choices(info, width), [])
                for text in ("✓ Wait for 19:59", "⇄ Go on now with acme-small",
                             *menu.detail(self.cfg, info, width)):
                    self.assertEqual(menu.choice_cells(text, info, width), [])

    def test_room_on_another_provider_keeps_both_choices(self):
        info = self.cache(20)
        self.assertEqual(info["go_on"], "zeta")
        self.assertEqual(menu.detail(self.cfg, info, 80), ["Acme has no usage left until 19:59."])
        self.assertEqual(menu.choice_lines(info, 80), [[
            ("✓ Wait for 19:59", menu.WAIT), ("⇄ Go on now with zeta", menu.GO_ON)]])
        self.assertEqual([terminal.ANSI.sub("", line) for line in menu.choices(info, 80)],
                         ["✓ Wait for 19:59   ⇄ Go on now with zeta"])
        self.assertEqual(menu.choice_cells("✓ Wait for 19:59   ⇄ Go on now with zeta", info, 80),
                         [(1, 16, menu.WAIT), (20, 40, menu.GO_ON)])


if __name__ == "__main__":
    unittest.main()
