"""The owner spends a usage-limit reset by hand, from its subscription's meter; offline.

A subscription's line under the grid of `ak` says `1 reset in hand` (`2 resets in hand`) while it
holds any, and nothing with none.  The row its meter opens, on `ak` and `c` alike, then offers
`→ spend a reset` after `→ log in again`, which its login ending soon offers, Enter on its line
never landing on the spend; it spends exactly one through `usage.replenish` -- the only caller of
it in ak -- and the row shows the week that came back.  A fake Codex adapter answers every verb
in a temporary HOME.
"""

from contextlib import ExitStack
import itertools
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
AGAIN, REMOVE = "[→ log in again]", "− remove"     # a line opens lit on the first, where offered


# The owner spends one by hand, from its meter. [2 Oct, 20 Oct 2026]
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
        # room for a line's every act beside its login's end
        stack.enter_context(patch.object(terminal, "layout_width", return_value=160))
        config.ensure_dirs()
        cfg = config.load()
        cfg["providers"] = {"openai": {**cfg["providers"]["openai"],
                                       "accounts": ["default", "second"]}}
        cfg["models"] = {n: e for n, e in cfg["models"].items() if e["provider"] == "openai"}
        self.cfg = cfg
        soon = {"ends": time.time() + 2 * 86400}
        (config.STATE / "logins.json").write_text(json.dumps({"openai": {
            "default": soon, "second": soon}}))
        stack.enter_context(patch.object(usage, "_probe_every", return_value=0))
        # each subscription by the name its adapter is told: "" the usual login
        self.used, self.held, self.spent = {"": 100, "second": 100}, {"": 2, "second": 1}, []
        # the kinds a usage answer counts its resets by, where it does; the kinds each spend
        # named; and whether every usage ask is refused
        self.kinds, self.named, self.refusing = {}, [], False
        until = time.time() + WEEK / 2

        def adapter(argv, env=None, **_kw):
            # `usage` is told its account on its command line, the reset verbs in their env
            account = (env[config.ACCOUNT_ENV] if env else argv[1].split("=", 1)[1])
            verb = argv[1] if env else argv[-1]
            if verb == "reset":
                self.spent.append(account)
                self.named.append(argv[2:])
                self.held[account] -= 1
                self.used[account] = 0
            counted = ({"resets": self.held[account], "reset_kinds": self.kinds[account]}
                       if account in self.kinds else {})
            data = ({"meters": [], "error": "unknown: HTTP 429 from acme.test"}
                    if verb == "usage" and self.refusing
                    else {"meters": [{"name": "weekly", "used": self.used[account],
                                      "resets_at": until, "window_secs": WEEK}], **counted}
                    if verb == "usage"
                    else {"available": self.held[account]} if verb == "reset-status"
                    else {"code": "reset", "available": self.held[account], "weekly_used": 0,
                          "resets_at": until})
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

        stack.enter_context(patch.object(config, "run_adapter", side_effect=adapter))

    def rows(self):
        """What the line under the usage grid says of each subscription, the pointer on it."""
        return [terminal.plain(menu.usage_detail(self.cfg, number))
                for number in range(1, len(menu.usage_cells(self.cfg)) + 1)]

    def offered(self, number, *keys):
        """The acts on subscription `number`'s line as Subscriptions opens on it, as its meter
        opens it, the lit one bracketed, `keys` (`right`, `enter`) then Esc read there; what
        the page said last is `self.note`."""
        drawn, keys = [], iter([*keys, "back"])

        def matrix_key(_title, body, _places, _rows, here, top, said, *_a, **_kw):
            row = next(at for at, line in enumerate(body) if line.startswith("›"))
            # its acts' line: the last it opens, under any of its limits
            opened = (terminal.plain(line, spaced=True) for line in body[row + 1:])
            *_, acts = itertools.takewhile(lambda line: line.startswith("    "), opened)
            drawn.append((acts.strip().split("   ")[1:], said))
            return next(keys), here, None, top
        config.save(self.cfg)       # the page reads config.toml as it opens
        with patch.object(menu, "matrix_key", side_effect=matrix_key):
            menu.config_subscriptions(self.cfg, None, number)
        self.note = drawn[-1][1]
        return drawn[0][0]

    def test_a_usage_row_says_the_resets_its_subscription_holds(self):
        usage.collect(self.cfg, refresh=True)
        first, second = self.rows()
        self.assertRegex(first, r"^ChatGPT I login ends .* · resets .* · 2 resets in hand$")
        self.assertRegex(second, r"^ChatGPT II login ends .* · resets .* · 1 reset in hand$")
        self.assertEqual(self.offered(1), [AGAIN, "→ spend a reset", REMOVE])
        self.held.update({"": 0, "second": 0})
        (config.STATE / "usage.json").unlink()
        usage.collect(self.cfg, refresh=True)
        self.assertFalse(any("in hand" in row for row in self.rows()), self.rows())
        self.assertEqual(self.offered(1), [AGAIN, REMOVE])
        self.assertEqual(menu.in_hand({"resets": None}), "")

    def test_a_meter_spends_one_of_its_own_and_shows_the_week_back(self):
        usage.collect(self.cfg, refresh=True)
        self.assertEqual(self.offered(2, "right", "enter"), [AGAIN, "→ spend a reset", REMOVE])
        self.assertEqual(self.spent, ["second"])          # exactly one, of the meter picked
        self.assertEqual(self.note, "ChatGPT II · 100% left")
        self.assertEqual(self.offered(2), [AGAIN, REMOVE])     # none left to spend
        self.offered(1)                                   # Esc on its line spends nothing
        self.assertEqual(self.spent, ["second"])

    def test_a_spend_of_a_kind_stands_as_its_own_answer_read_it(self):
        # resets counted by kind, a spend whose answer names none, and every probe after it
        # refused: the kind spent holds one less, and nothing puts back the week it replaced
        self.kinds[""] = [{"kind": "weekly", "left": 1, "usable": True},
                          {"kind": "Fable", "left": 1, "usable": True}]
        usage.collect(self.cfg, refresh=True)
        self.refusing = True
        self.assertEqual(self.offered(1, "right", "right", "enter"),
                         [AGAIN, "→ spend a weekly reset", "→ spend a Fable reset", REMOVE])
        self.assertEqual(self.named, [["Fable"]])
        self.assertEqual(self.note, "ChatGPT I · 100% left · 1 weekly reset in hand")
        self.assertRegex(self.rows()[0], r" · 1 weekly reset in hand$")

    def test_a_meter_reads_its_week_back_by_its_name_as_written(self):
        self.cfg["providers"]["openai"]["name"] = "Acme  Plan"     # spaced as its owner typed it
        usage.collect(self.cfg, refresh=True)
        self.offered(2, "right", "enter")
        self.assertEqual(self.note, "Acme  Plan II · 100% left")

    def test_of_two_subscriptions_of_one_name_a_meter_spends_its_own(self):
        rows = [("openai", "ChatGPT", {}, None), ("acme", "ChatGPT", {"resets": 1}, None)]
        with patch.object(menu, "usage_rows", return_value=rows), \
                patch.object(usage, "replenish", return_value=(False, 1)) as replenish:
            self.assertEqual(self.offered(1), [AGAIN, REMOVE])     # not its own
            self.offered(2, "right", "enter")
        # with the config the page read
        replenish.assert_called_once_with(config.load(), "acme", account=None, kind=None)

    def test_only_the_owners_act_spends_one(self):
        callers = [(path.name, inside) for path in sorted((REPO / "agentkit").rglob("*.py"))
                   for inside, _ in calls(path, "replenish")]
        self.assertEqual(callers, [("menu.py", "config_spend_reset")])


if __name__ == "__main__":
    unittest.main()
