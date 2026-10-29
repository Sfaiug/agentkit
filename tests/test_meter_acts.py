"""A meter offers the same on the ak screen and on `c`, and only `Subscriptions` removes.

The owner (20 Oct 2026): "Pressing on the usage meters inside the config and on the menu has a
different effect, should always be the same one. I dont want removing to be able this way, just
actions such as spendign a reset, or claude relogin".  Enter on a meter over `c` lists what a
click on one on the ak screen lists (tests/test_login_click.py), `↻ log in again` and `↻ spend a
reset` while one is in hand, never `− remove`, which is under each subscription's row on
`Subscriptions`.  `log in again` only where its harness signs in afresh: Antigravity's usual
login cannot (`[auth] again = false`).  In-process, in a temporary HOME: `c`'s key reader faked and every list let go,
so nothing is signed in, spent or removed.
"""

from contextlib import redirect_stdout
import io
import json
import re
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, terminal

WEEK = {"name": "weekly", "resets_at": 10000 + 3 * 86400, "window_secs": 604800, "used": 50}


class MeterActs(Sandbox):
    def setUp(self):
        super().setUp()
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [WEEK], "resets": 1}, "openai": {"meters": [WEEK]}}}))
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

    def test_a_meter_on_c_lists_what_it_does_and_never_removes(self):
        self.keyed(lambda: menu.config_matrix(self.cfg, None, "abc1234"),
                   [*(("enter", ("usage", number)) for number in range(1, len(self.rows) + 1)),
                    ("back", None)])
        # Gemini's holds no reset and its harness cannot sign in afresh: its meter lists nothing
        self.assertEqual(self.offered, [["↻ log in again", "↻ spend a reset"] if row == "Claude"
                                        else ["↻ log in again"]
                                        for row in self.rows if row != "Gemini"])

    def test_subscriptions_lists_every_subscription_with_its_removal_under_it(self):
        chatgpt, gemini = self.rows.index("ChatGPT") + 1, self.rows.index("Gemini") + 1
        drawn = self.keyed(lambda: menu.config_subscriptions(self.cfg, None),
                           [(None, ("sub", chatgpt)), (None, ("sub", gemini)), ("back", None)])
        self.assertEqual([re.split(r"\s{2,}", line[2:])[0] for line in drawn[0]
                          if line[:1] in " ›" and line[2:3].strip()],
                         [*self.rows, "+ add a subscription"])

        def under(lines, label):      # the line the row of `label` opens, as it reads
            return lines[next(at for at, line in enumerate(lines)
                              if line[2:].startswith(label + " ")) + 1].strip().split("   ")
        self.assertEqual(under(drawn[0], "Claude"),
                         ["[↻ log in again]", "↻ spend a reset", "− remove"])
        self.assertEqual(under(drawn[1], "ChatGPT"), ["[↻ log in again]", "− remove"])
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
                           ("login_notes", lambda _subs: [None]),
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
        self.stack.enter_context(patch.object(terminal, "layout_width", return_value=30))
        drawn = self.keyed(lambda: menu.config_subscriptions(self.cfg, None), [("back", None)])
        self.assertEqual(drawn[0][1:3], ["› Claude   ▰▰▰▰▱▱▱▱  50% left",
                                          "    1 reset in hand"])

    def test_the_last_row_removed_leaves_the_highlight_on_the_new_last(self):
        last = len(self.rows) - 1
        self.assertEqual(self.drive(*["down"] * last, "right", "right", "enter", "down",
                                    "enter"), ([], [self.rows[last]]))

    def test_a_page_with_no_subscription_still_adds_one(self):
        added = []
        self.stack.enter_context(patch.object(menu, "usage_rows", return_value=[]))
        self.stack.enter_context(patch.object(menu, "config_add_provider",
                                              side_effect=lambda *_a: added.append(1)))
        self.assertEqual(self.drive("enter"), ([], []))
        self.assertEqual(added, [1])


if __name__ == "__main__":
    unittest.main()
