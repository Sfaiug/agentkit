"""The scoreboard shows the owner's time each week: the questions seats asked them, the cards
sent to them, and the median hours a question answered that week had waited since it was last
asked.  notify writes each moment as it decides it -- a question new to a notice, a card
delivered, each standing question answered, by the owner's prompt or, where nothing reports or
reads one, by output after an open -- as a row naming no seat.  A moment on the boundary between
the weeks counts in the last 7 days only.  A new install, with no database, shows `not
recorded`.

Offline: a sandbox HOME with its own history database, the webhook post faked, git answering
nothing.
"""

import sys
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import history, notify, scoreboard, terminal

SEAT = "fix-api"
NOW = 1_800_000_000
WEEK = 7 * 86400
HOUR = 3600


class OwnerRow(Sandbox):
    def setUp(self):
        super().setUp()
        for target, name, value in ((scoreboard, "_git", lambda *args, **kw: None),
                                    (scoreboard.time, "time", lambda: NOW),
                                    (terminal, "content_width", lambda: 400)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def said(self, kind, text, at, event_id=None):
        with notify.session_lock(SEAT) as name:
            notify._said(name, kind, text, event_id=event_id, at=at)

    def attempt(self, status, now):
        def post(payload, files, message, receipt=None):
            receipt.update(status=status, message_id="m1", webhook="w")

        event = {"id": f"e{now}", "session": SEAT, "kind": "needs", "text": "words", "files": [],
                 "payload": {"username": "agentkit", "embeds": [{}]}, "message": "m",
                 "created_at": now, "sink": notify.sink() is not None,
                 "status": "pending", "attempts": 0, "next_attempt": 0}
        # under the outbox lock, as the card queue and the tick's retry call it
        with patch.object(notify, "webhook", return_value="https://hooks.invalid/x"), \
                patch.object(notify, "post", post), \
                patch.object(notify.time, "time", return_value=now), notify.outbox_lock():
            notify._attempt(event)

    def moments(self):
        return history.owner(0, NOW)

    def test_notify_writes_each_moment_as_it_decides_it(self):
        self.said("needs", "Which schema?", 100.0)
        self.said("needs", "And the port?", 160.0)        # asked beside the standing one
        self.said("needs", "Which schema?", 170.0)        # asked again: not a new question
        self.said("needs", "GitHub is logged out", 180.0, event_id="auth:gh")    # ak's own alert
        self.attempt("delivered", 190.0)
        self.attempt("pending", 195.0)                    # a card not delivered sent nothing
        asked = [(100.0, "asked", None), (160.0, "asked", None), (190.0, "paged", None)]
        self.assertCountEqual(self.moments(), asked)
        # the owner's one prompt answers both, each from when it was last asked
        notify.answered(SEAT, 350.0)
        notify.answered(SEAT, 400.0)      # nothing stands: no answer
        self.assertCountEqual(self.moments(), [*asked, (350.0, "answered", 180.0),
                                               (350.0, "answered", 190.0)])

    def test_output_after_an_open_answers_where_nothing_reports_or_reads_one(self):
        self.said("needs", "Which schema?", 100.0)
        with patch.object(notify.time, "time", return_value=150.0):
            notify.opened(SEAT, lambda: "Reading the parser")
        with patch.object(notify.time, "time", return_value=200.0):
            self.assertTrue(notify.progress(SEAT, lambda: "Shipping the parser", None))
        self.assertCountEqual(self.moments(), [(100.0, "asked", None), (200.0, "answered", 100.0)])

    def test_questions_cards_and_waits_count_in_the_week_each_happened(self):
        for at, kind, waited in ((NOW - 10 * HOUR, "asked", None), (NOW - 9 * HOUR, "paged", None),
                                 (NOW - 8.5 * HOUR, "answered", 1.5 * HOUR),
                                 (NOW - 4 * HOUR, "asked", None), (NOW - 3.5 * HOUR, "answered", 0.5 * HOUR),
                                 (NOW - 1 * HOUR, "paged", None), (NOW - 0.5 * HOUR, "paged", None),
                                 # asked last week, answered this week after three hours
                                 (NOW - WEEK - HOUR, "asked", None), (NOW - WEEK - 0.9 * HOUR, "paged", None),
                                 (NOW - WEEK + 2 * HOUR, "answered", 3 * HOUR)):
            history.owner_time(kind, at, waited)
        board = scoreboard.compute(NOW)
        self.assertEqual(board["owner"], [{"asked": 2, "paged": 3, "hours": 1.5},
                                          {"asked": 1, "paged": 1, "hours": None}])
        row = [line for line in scoreboard.render() if line.startswith("owner")][0]
        self.assertIn("2 questions asked, 3 cards sent, median 1.5 hours waiting for an answer", row)
        self.assertIn("1 questions asked, 1 cards sent", row)
        self.assertNotIn("1 questions asked, 1 cards sent, median", row)

    def test_a_moment_on_the_boundary_counts_in_the_last_7_days(self):
        for kind, waited in (("asked", None), ("paged", None), ("answered", HOUR)):
            history.owner_time(kind, NOW - WEEK, waited)
        self.assertEqual(scoreboard.compute(NOW)["owner"], [{"asked": 1, "paged": 1, "hours": 1.0},
                                                            {"asked": 0, "paged": 0, "hours": None}])

    def test_a_new_install_shows_not_recorded(self):
        self.assertFalse(history.path().exists())
        self.assertIsNone(history.owner(NOW - WEEK, NOW))
        self.assertEqual(scoreboard.compute(NOW)["owner"], [None, None])
        self.assertIn("owner     not recorded", "\n".join(scoreboard.render()))


if __name__ == "__main__":
    unittest.main()
