"""ak never types a line into a composer holding the owner's text, on any of its typing paths.

A seat's handover after a switch was typed ten seconds after launch into the owner's
half-written prompt and sent the two as one message.  fixtures.seats' throwaway seats, with a
faked pane and tmux: no tmux server or real harness.
"""

import unittest
from unittest import mock

from fixtures.seats import NOW, SEAT, Seats
from agentkit import watch

DRAFT = "half a thought about the parser"


class NoLineOverADraft(Seats):
    def drafted(self):
        self.pane = self.base.replace(self.empty, "❯ " + DRAFT + "\n")

    def test_a_line_waits_while_the_composer_holds_the_owners_text(self):
        self.drafted()
        self.assertIsNone(watch.type_into(self.seat, "continue", lambda _: None))
        self.assertEqual(self.typed, [])
        self.assertEqual(self.receipts(), [])
        self.pane = self.base
        self.assertTrue(watch.type_into(self.seat, "continue", lambda _: None))
        self.assertEqual(self.typed, ["continue"])

    def test_a_relaunched_seats_line_keeps_its_tries_until_the_draft_is_gone(self):
        for line in (watch.MIDTURN_LINE, watch.ACCOUNT_LINE,
                     "You took over this seat from astra."):
            with self.subTest(line=line[:20]):
                self.typed.clear()
                self.drafted()
                accounts = line == watch.ACCOUNT_LINE
                mark = {"boot": watch.boot_id(), "at": NOW - 100, "name": SEAT,
                        "tries": watch.MIDTURN_TRIES - 1, "line": line,
                        **({"account": True} if accounts else {})}
                watch.seat_write(SEAT, midturn=mark)
                for _ in range(watch.MIDTURN_TRIES + 1):
                    watch.continue_turns(self.cfg, lambda _: None, accounts=accounts)
                self.assertEqual(self.typed, [])
                self.assertEqual(watch.seat_read(SEAT).get("midturn"), mark)
                self.pane = self.base
                watch.continue_turns(self.cfg, lambda _: None, accounts=accounts)
                self.assertEqual(self.typed, [line])
                self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def test_a_handover_whose_enter_failed_gets_that_enter_later(self):
        line = "You took over this seat from astra."
        watch.seat_write(SEAT, midturn={"boot": watch.boot_id(), "at": NOW - 100,
                                       "name": SEAT, "line": line})
        enter, failed = watch._send_enter, []
        with mock.patch.object(watch, "_send_enter", side_effect=lambda session, log: (
                enter(session, log) if failed else failed.append(1))):
            watch.continue_turns(self.cfg, lambda _: None)
            watch.finish_own_lines(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [line])
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
