"""A hand-back typed into a seat is sent there, never typed into a second seat.

Offline: fake seats, a fake fallback and a typer that keeps `type_at_prompt`'s mark rule
(a mark naming the seat by its `created` gets only Enter; any other seat is typed fresh).
"""

from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import orch, watch

KEY = "github.com/acme/widget"
LINE = "The acme harness gate failed: fix it."


class StaysWithItsSeat(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.a = {"name": "fix-api", "created": 100, "exited": False}
        self.b = {"name": "fix-ui", "created": 200, "exited": False}
        self.rows, self.fallback, self.keys, self.mark = [self.a], self.a, [], None
        stack.enter_context(patch.object(orch, "sessions", lambda: list(self.rows)))
        stack.enter_context(patch.object(watch, "after_merge_fallback",
                                         lambda key: self.fallback))
        stack.enter_context(patch.object(watch, "type_at_prompt", self.type_line))

    def type_line(self, seat, line, log, cfg=None, typed=None, receipt=lambda mark: None, **_kw):
        mark = {"line": line, "seat": seat.get("created")}
        self.keys.append((seat["name"], "enter" if typed == mark else "line"))
        receipt(mark)
        return False            # the Enter never lands

    def deliver(self):
        def keep(mark):
            self.mark = mark
        watch.after_merge_deliver(None, {}, KEY, LINE, lambda _: None, typed=self.mark,
                                  receipt=keep)

    def typed_into_a_then_b_qualifies(self):
        self.deliver()
        self.assertEqual(self.keys, [("fix-api", "line")])
        self.rows, self.fallback = [self.a, self.b], self.b

    def test_the_next_pass_presses_enter_in_the_seat_holding_the_line(self):
        self.typed_into_a_then_b_qualifies()
        self.deliver()
        self.deliver()
        self.assertEqual(self.keys, [("fix-api", "line"), ("fix-api", "enter"),
                                     ("fix-api", "enter")])

    def test_a_renamed_seat_is_the_same_seat(self):
        self.typed_into_a_then_b_qualifies()
        self.rows = [dict(self.a, name="fix-api-2"), self.b]
        self.deliver()
        self.assertEqual(self.keys[1:], [("fix-api-2", "enter")])

    def test_once_that_seat_is_gone_or_reopened_the_fallback_gets_it_fresh(self):
        for gone in ({**self.a, "exited": True}, {**self.a, "created": 300}, None):
            with self.subTest(a=gone):
                self.keys, self.mark = [], None
                self.rows, self.fallback = [self.a], self.a
                self.typed_into_a_then_b_qualifies()
                self.rows = [seat for seat in (gone, self.b) if seat]
                self.deliver()
                self.assertEqual(self.keys[1:], [("fix-ui", "line")])
                self.deliver()
                self.assertEqual(self.keys[2:], [("fix-ui", "enter")])


if __name__ == "__main__":
    unittest.main()
