"""`c`'s `Subscriptions` is a page of rows: each subscription, its list under it offering what its
meter does.

The owner (20 Oct 2026): "in the config instead of having add model and add provider, it should
instead be just provider options and settings".  In-process, in a temporary HOME: the page's key
reader faked, so nothing is spent or removed.
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


class SubscriptionsPage(Sandbox):
    def setUp(self):
        super().setUp()
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": 10000, "providers": {
            "anthropic": {"meters": [WEEK], "resets": 1}, "openai": {"meters": [WEEK]}}}))
        self.rows = [label for _, label, _, _ in menu.usage_rows(self.cfg)]
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def test_every_subscription_has_a_row_with_what_it_offers_under_it(self):
        claude, chatgpt = self.rows.index("Claude"), self.rows.index("ChatGPT")
        drawn, script = [], iter([("enter", ("row", claude)), ("back", None),
                                  ("enter", ("row", chatgpt)), ("back", None), ("back", None)])

        def matrix_key(_title, body, _places, _rows, here, top, *_args, **_kwargs):
            drawn.append([terminal.plain(line, spaced=True) for line in body])
            act, row = next(script)
            return act, row or here, None, top
        with patch.object(menu, "matrix_key", side_effect=matrix_key):
            menu.config_subscriptions(self.cfg, None)
        self.assertEqual([re.split(r"\s{2,}", line[2:])[0] for line in drawn[0]],
                         self.rows)

        def under(lines, at, count):      # the list drawn under row `at`, as it reads
            return [line[2:].strip() for line in lines[at + 1:at + 1 + count]]
        self.assertEqual(under(drawn[1], claude, 2), ["↻ spend a reset", "− remove"])
        self.assertEqual(under(drawn[3], chatgpt, 1), ["− remove"])

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
