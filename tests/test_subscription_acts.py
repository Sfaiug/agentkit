"""A subscription's acts have one home: its line on `Subscriptions`, which Enter on its meter
over `c` opens on its row, as a click on one on the ak screen does (tests/test_login_click.py).
The line offers `→ log in again` while its login ends soon (here every one's does) and its harness
signs in afresh -- Antigravity's usual login cannot (`[auth] again = false`) -- `→ spend a reset`
while one is in hand, and `− remove`.  In-process, in a temporary HOME: the screens' key reader
faked and every list let go, so nothing is signed in, spent or removed but where a test says.
"""

from contextlib import redirect_stdout
import io
import itertools
import json
import re
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, terminal

WEEK = {"name": "weekly", "resets_at": 10000 + 3 * 86400, "window_secs": 604800, "used": 50}


class SubscriptionActs(Sandbox):
    def setUp(self):
        super().setUp()
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [WEEK], "resets": 1}, "openai": {"meters": [WEEK]}}}))
        soon = {"default": {"ends": 10000 + 2 * 86400}}
        (config.STATE / "logins.json").write_text(json.dumps(
            {provider: soon for provider in self.cfg["providers"]}))
        self.rows = [label for _, label, _, _ in menu.usage_rows(self.cfg)]
        self.offered = []
        self.stack.enter_context(patch.object(terminal, "choose", side_effect=lambda choices, *_a,
                                              **_kw: self.offered.append(choices)))   # let go
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def keyed(self, screen, acts):
        """`screen` read with `acts`, (act, row) each, for its keys, as `c`'s key reader gives
        them; the lines it drew, each time it read one."""
        drawn, script = [], iter(acts)

        def matrix_key(_title, body, _places, _rows, here, top, *_args, **_kwargs):
            drawn.append([terminal.plain(line, spaced=True) for line in body])
            act, row = next(script)
            return act, row or here, None, top
        with patch.object(menu, "matrix_key", side_effect=matrix_key):
            screen()
        return drawn

    def test_enter_on_a_meter_on_c_opens_its_row_on_subscriptions(self):
        drawn = self.keyed(lambda: menu.config_matrix(self.cfg, None, "abc1234"),
                           [*(act for number in range(1, len(self.rows) + 1)
                              for act in [("enter", ("usage", number)), ("back", None)]),
                            ("back", None)])
        # the row each page opened on, of the pages drawn
        self.assertEqual([re.split(r"\s{2,}", line[2:])[0] for lines in drawn
                          if "  + add a subscription" in lines
                          for line in lines if line.startswith("› ")], self.rows)
        self.assertEqual(self.offered, [])         # its row, no list of its own

    def test_subscriptions_lists_every_subscription_with_its_removal_under_it(self):
        chatgpt, gemini = self.rows.index("ChatGPT") + 1, self.rows.index("Gemini") + 1
        drawn = self.keyed(lambda: menu.config_subscriptions(self.cfg, None),
                           [(None, ("sub", chatgpt)), (None, ("sub", gemini)), ("back", None)])
        self.assertEqual([re.split(r"\s{2,}", line[2:])[0] for line in drawn[0]
                          if line[:1] in " ›" and line[2:3].strip()],
                         [*self.rows, "+ add a subscription"])

        def under(lines, label):      # the acts the row of `label` opens, as their line reads:
            # the last line it opens, under any of its limits
            at = next(at for at, line in enumerate(lines) if line[2:].startswith(label + " "))
            *_, acts = itertools.takewhile(lambda line: line.startswith("    "), lines[at + 1:])
            return acts.strip().split("   ")[1:]
        self.assertEqual(under(drawn[0], "Claude"),
                         ["[→ log in again]", "→ spend a reset", "− remove"])
        self.assertEqual(under(drawn[1], "ChatGPT"), ["[→ log in again]", "− remove"])
        self.assertEqual(under(drawn[2], "Gemini"), ["− remove"])    # lit only by a move
        self.assertEqual(self.offered, [])         # the page's own line, no other list

    def test_enter_runs_the_act_drawn_while_its_reading_moves(self):
        # The owner moves onto `− remove` and a probe brings a reset in as Enter is pressed:
        # Enter removes, and spends nothing.
        reading, removed, spent = {}, [], []
        keys = iter([terminal.Key("right"), terminal.Key("enter"), terminal.Key("esc")])

        def read(*_args, **_kwargs):
            key = next(keys)
            if key.name == "enter":
                reading["resets"] = 1
            return key
        for name, fake in (("usage_rows", lambda _cfg: [("anthropic", "Claude", dict(reading),
                                                          None)]),
                           ("login_notes", lambda _subs, *_a: [(None, None, None)]),
                           ("config_spend_reset", lambda *_a: spent.append("Claude")),
                           ("config_remove_provider", lambda *_a: removed.append("Claude"))):
            self.stack.enter_context(patch.object(menu, name, side_effect=fake))
        self.stack.enter_context(patch.object(terminal, "read_key", side_effect=read))
        self.stack.enter_context(patch.object(terminal, "frame", return_value={}))
        menu.config_subscriptions(self.cfg, None)
        self.assertEqual((spent, removed), ([], ["Claude"]))

    def drive(self, *keys):
        """The page read with `keys`, then Esc, nothing spent: (signed in again, removed)."""
        signed, removed, keys = [], [], iter(map(terminal.Key, [*keys, "esc"]))

        def remove(cfg, picked):
            removed.append(picked[2])
            del cfg["providers"][picked[0]]
            return ""
        for name, fake in (("config_spend_reset", AssertionError),
                           ("sign_in", lambda _cfg, _kb, picked: signed.append(picked[0]) or ""),
                           ("config_remove_provider", remove)):
            self.stack.enter_context(patch.object(menu, name, side_effect=fake))
        self.stack.enter_context(patch.object(terminal, "read_key",
                                              side_effect=lambda *_a, **_kw: next(keys)))
        self.stack.enter_context(patch.object(terminal, "frame", return_value={}))
        menu.config_subscriptions(self.cfg, None)
        return signed, removed

    def test_enter_on_a_reset_in_hand_signs_in_again_never_spends_nor_removes(self):
        # The first act is lit as the line opens: the spend and the removal are a move away.
        self.assertEqual(self.drive("enter"), (["anthropic"], []))

    def test_resets_with_no_room_beside_the_meter_are_on_its_line(self):
        (config.STATE / "logins.json").unlink()       # its line says no login ending first
        self.stack.enter_context(patch.object(terminal, "layout_width", return_value=30))
        drawn = self.keyed(lambda: menu.config_subscriptions(self.cfg, None), [("back", None)])
        self.assertEqual(drawn[0][1:4], [
            "› Claude   ━━━━────  50% left",
            time.strftime("    resets %a %H:%M", time.localtime(WEEK["resets_at"])),
            "    1 reset in hand"])

    def test_the_last_row_removed_leaves_the_highlight_on_the_new_last(self):
        last = len(self.rows) - 1
        # Enter there opens `+ add a subscription`, which Esc leaves, no subscription's act run
        self.assertEqual(self.drive(*["down"] * last, "right", "right", "enter", "down",
                                    "enter", "esc"), ([], [self.rows[last]]))

    def test_a_page_with_no_subscription_still_adds_one(self):
        added = []
        self.stack.enter_context(patch.object(menu, "usage_rows", return_value=[]))
        self.stack.enter_context(patch.object(menu, "config_add_provider",
                                              side_effect=lambda *_a: added.append(1)))
        self.assertEqual(self.drive("enter"), ([], []))
        self.assertEqual(added, [1])


if __name__ == "__main__":
    unittest.main()
