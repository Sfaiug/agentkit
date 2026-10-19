"""The owner spends a usage-limit reset by hand, from its subscription's meter on `c`; offline.

A subscription's line under the grid of `ak` says `1 reset in hand` (`2 resets in hand`) while it
holds any, and nothing with none.  Its meter over the page of `c` then offers `↻ spend a reset`
beside `− remove`, Enter on the list never landing on the spend; it spends
exactly one through `usage.replenish` -- the only caller of it in ak -- and the row shows the
week that came back.  A fake Codex adapter answers every verb in a temporary HOME.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, terminal, usage  # noqa: E402
from test_reset_never_automatic import calls  # noqa: E402

WEEK = 604800


class ResetByHand(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(
            prefix=".ak-test-reset-by-hand-", dir=REPO)))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(root), "NO_COLOR": "1",
                                                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        config.ensure_dirs()
        cfg = config.load()
        cfg["providers"] = {"openai": {**cfg["providers"]["openai"],
                                       "accounts": ["default", "second"]}}
        cfg["models"] = {n: e for n, e in cfg["models"].items() if e["provider"] == "openai"}
        self.cfg = cfg
        stack.enter_context(patch.object(usage, "_probe_every", return_value=0))
        # each subscription by the name its adapter is told: "" the usual login
        self.used, self.held, self.spent = {"": 100, "second": 100}, {"": 2, "second": 1}, []
        until = time.time() + WEEK / 2

        def adapter(argv, env=None, **_kw):
            # `usage` is told its account on its command line, the reset verbs in their env
            account = (env[config.ACCOUNT_ENV] if env else argv[1].split("=", 1)[1])
            verb = argv[-1]
            if verb == "reset":
                self.spent.append(account)
                self.held[account] -= 1
                self.used[account] = 0
            data = ({"meters": [{"name": "weekly", "used": self.used[account],
                                 "resets_at": until, "window_secs": WEEK}]} if verb == "usage"
                    else {"available": self.held[account]} if verb == "reset-status"
                    else {"code": "reset", "available": self.held[account], "weekly_used": 0,
                          "resets_at": until})
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

        stack.enter_context(patch.object(usage.subprocess, "run", side_effect=adapter))

    def rows(self):
        """What the line under the usage grid says of each subscription, the pointer on it."""
        return [terminal.plain(menu.usage_detail(self.cfg, number))
                for number in range(1, len(menu.usage_cells(self.cfg)) + 1)]

    def offered(self, number, picked=None):
        """What subscription `number`'s meter on `c` lists and picks first, `picked` taken; a
        meter offering only `− remove` lists nothing and asks at once."""
        asked = []
        with patch.object(terminal, "choose", side_effect=lambda choices, default=None, **_kw:
                          asked.append((choices, default)) or picked), \
                patch.object(terminal, "frame"), \
                patch.object(menu, "config_remove_provider",
                             side_effect=lambda *_a: asked.append("removed") or ""):
            self.note = menu.config_usage(self.cfg, number)
        return asked

    def test_a_usage_row_says_the_resets_its_subscription_holds(self):
        usage.collect(self.cfg, refresh=True)
        first, second = self.rows()
        self.assertRegex(first, r"^ChatGPT I resets .* · 2 resets in hand$")
        self.assertRegex(second, r"^ChatGPT II resets .* · 1 reset in hand$")
        self.assertEqual(self.offered(1), [(["↻ spend a reset", "− remove"], "− remove")])
        self.held.update({"": 0, "second": 0})
        (config.STATE / "usage.json").unlink()
        usage.collect(self.cfg, refresh=True)
        self.assertFalse(any("in hand" in row for row in self.rows()), self.rows())
        self.assertEqual(self.offered(1), ["removed"])
        self.assertEqual(menu.in_hand({"resets": None}), "")

    def test_a_meter_spends_one_of_its_own_and_shows_the_week_back(self):
        usage.collect(self.cfg, refresh=True)
        self.assertEqual(self.offered(2, "↻ spend a reset"),
                         [(["↻ spend a reset", "− remove"], "− remove")])
        self.assertEqual(self.spent, ["second"])          # exactly one, of the meter picked
        self.assertEqual(self.note, "ChatGPT II · 100% left")
        self.assertEqual(self.offered(2), ["removed"])   # none left there to spend
        self.offered(1)                                   # Esc on the list spends nothing
        self.assertEqual(self.spent, ["second"])

    def test_a_meter_reads_its_week_back_by_its_name_as_written(self):
        self.cfg["providers"]["openai"]["name"] = "Acme  Plan"     # spaced as its owner typed it
        usage.collect(self.cfg, refresh=True)
        self.offered(2, "↻ spend a reset")
        self.assertEqual(self.note, "Acme  Plan II · 100% left")

    def test_of_two_subscriptions_of_one_name_a_meter_spends_its_own(self):
        rows = [("openai", "ChatGPT", {}, None), ("acme", "ChatGPT", {"resets": 1}, None)]
        with patch.object(menu, "usage_rows", return_value=rows), \
                patch.object(usage, "replenish", return_value=(False, 1)) as replenish:
            self.assertEqual(self.offered(1), ["removed"])      # the other's is not its own
            self.offered(2, "↻ spend a reset")
        replenish.assert_called_once_with(self.cfg, "acme", account=None)

    def test_only_the_owners_act_spends_one_and_the_docs_say_where(self):
        callers = [(path.name, inside) for path in sorted((REPO / "agentkit").rglob("*.py"))
                   for inside, _ in calls(path, "replenish")]
        self.assertEqual(callers, [("menu.py", "config_spend_reset")])
        text = (REPO / "docs/guide.md").read_text()
        self.assertIn("`↻ spend a reset` on its meter on `c`", text)
        self.assertIn("`1 reset in hand`", text)


if __name__ == "__main__":
    unittest.main()
