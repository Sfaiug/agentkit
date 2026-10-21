"""A meter offers the same on the ak screen and on `c`, and only `Subscriptions` removes.

The owner (20 Oct 2026): "Pressing on the usage meters inside the config and on the menu has a
different effect, should always be the same one. I dont want removing to be able this way, just
actions such as spendign a reset, or claude relogin".  Enter on a meter over `c` lists what a
click on one on the ak screen lists (tests/test_login_click.py), `↻ log in again` and `↻ spend a
reset` while one is in hand, never `− remove`, which is under each subscription's row on
`Subscriptions`.  `log in again` only where its harness signs in afresh: Antigravity's cannot
(`[auth] again = false`).  In-process, in a temporary HOME: `c`'s key reader faked and every list let go,
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
        claude, chatgpt = self.rows.index("Claude"), self.rows.index("ChatGPT")
        acts = [("enter", ("row", claude)), ("back", None),     # its list, opened and closed
                ("enter", ("row", chatgpt)), ("back", None), ("back", None)]
        drawn = self.keyed(lambda: menu.config_subscriptions(self.cfg, None), acts)
        self.assertEqual([re.split(r"\s{2,}", line[2:])[0] for line in drawn[0]],
                         [*self.rows, "+ add a subscription"])

        def under(lines, at, count):      # the list drawn under row `at`, as it reads
            return [line[2:].strip() for line in lines[at + 1:at + 1 + count]]
        self.assertEqual(under(drawn[1], claude, 3),
                         ["↻ log in again", "↻ spend a reset", "− remove"])
        self.assertEqual(under(drawn[3], chatgpt, 2), ["↻ log in again", "− remove"])
        self.assertEqual(self.offered, [])         # the page's own list, no other

    def test_an_open_list_stays_as_it_opened_while_its_reading_moves(self):
        # The owner moves onto `− remove` as a probe brings a reset in: Enter removes, and
        # spends nothing.
        reading, removed, spent = {}, [], []
        keys = iter([terminal.Key("enter"), terminal.Key("down"), terminal.Key("enter"),
                     terminal.Key("esc")])

        def read(*_args, **_kwargs):
            key = next(keys)
            if key.name == "down":
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


if __name__ == "__main__":
    unittest.main()
