"""The owner spends a usage-limit reset by hand, from the Providers row of `c`; offline.

A usage row on the `ak` menu says `1 reset in hand` (`2 resets in hand`) while its subscription
holds any, and nothing with none.  The Providers row of `c` then offers `↻ spend a reset` beside
`+ add` and `− remove`; it asks which subscription when more than one holds a reset, spends
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
        return [terminal.plain(line) for line in menu.usage_lines(self.cfg, 100)[1:]]

    def acts(self):
        return "".join(line for line, _ in menu.providers_lines(self.cfg, 13, 100))

    def test_a_usage_row_says_the_resets_its_subscription_holds(self):
        usage.collect(self.cfg, refresh=True)
        first, second = self.rows()
        self.assertRegex(first, r"^ChatGPT I .* 0% left · resets .* · 2 resets in hand$")
        self.assertRegex(second, r"^ChatGPT II .* 0% left · resets .* · 1 reset in hand$")
        self.assertIn("↻ spend a reset", self.acts())
        self.held.update({"": 0, "second": 0})
        (config.STATE / "usage.json").unlink()
        usage.collect(self.cfg, refresh=True)
        self.assertFalse(any("in hand" in row for row in self.rows()), self.rows())
        self.assertNotIn("spend a reset", self.acts())
        self.assertEqual(menu.in_hand({"resets": None}), "")

    def test_it_asks_which_subscription_spends_one_and_the_row_shows_the_week_back(self):
        usage.collect(self.cfg, refresh=True)
        asked = []

        def choose(choices, **_kw):
            asked.append(choices)
            return "ChatGPT II"
        with patch.object(terminal, "choose", side_effect=choose):
            note = menu.config_spend_reset(self.cfg)
        self.assertEqual(asked, [["ChatGPT I", "ChatGPT II"]])
        self.assertEqual(self.spent, ["second"])          # exactly one, on the one picked
        self.assertTrue(note.startswith("ChatGPT II · 100% left · resets "), note)
        first, second = self.rows()
        self.assertIn("2 resets in hand", first)
        self.assertRegex(second, r"^ChatGPT II .* 100% left · resets [^·]*$")
        # one subscription left holding one: nothing to ask, and it is the one spent from
        with patch.object(terminal, "choose", side_effect=choose):
            menu.config_spend_reset(self.cfg)
        self.assertEqual((len(asked), self.spent), (1, ["second", ""]))
        self.assertIn("1 reset in hand", self.rows()[0])

    def test_no_move_onto_providers_lands_on_spending_a_reset(self):
        usage.collect(self.cfg, refresh=True)
        model = config.offered(self.cfg)[0]
        selected = {"orchestrator": model, "workers": [model], "reviewers": [model]}
        ran, script = [], iter([
            ("right", ("model", model), None, 0), ("right", ("model", model), None, 0),
            ("down", menu.PROVIDERS, None, 0),        # from the reviewer mark, column 2
            ("enter", menu.PROVIDERS, None, 0),       # `− remove`, not the spend
            ("right", menu.PROVIDERS, None, 0), ("right", menu.PROVIDERS, None, 0),
            ("enter", menu.PROVIDERS, None, 0),
            ("back", menu.PROVIDERS, None, 0)])
        with patch("agentkit.watch.worker_token_note", return_value=None), \
                patch.object(menu, "matrix_key", side_effect=lambda *a, **k: next(script)), \
                patch.object(menu, "config_remove_provider",
                             side_effect=lambda cfg: ran.append("remove") or ""), \
                patch.object(menu, "config_spend_reset",
                             side_effect=lambda cfg: ran.append("spend") or ""):
            menu.config_matrix(self.cfg, None, "abc1234", "fix-api", selected, {})
        self.assertEqual(ran, ["remove", "spend"])
        self.assertEqual(self.spent, [])

    def test_only_the_owners_act_spends_one_and_the_docs_say_where(self):
        callers = [(path.name, inside) for path in sorted((REPO / "agentkit").rglob("*.py"))
                   for inside, _ in calls(path, "replenish")]
        self.assertEqual(callers, [("menu.py", "config_spend_reset")])
        for doc in ("README.md", "docs/guide.md"):
            text = (REPO / doc).read_text()
            self.assertIn("`↻ spend a reset` on the Providers row of `c`", text, doc)
            self.assertIn("`1 reset in hand`", text, doc)


if __name__ == "__main__":
    unittest.main()
