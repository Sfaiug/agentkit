"""The owner's moments are recorded in history as they happen, for the board: `notices`, one
row per word a seat's notice said to them (a question the seat asked, an alert of ak's own, a
done), dated at the notice, with when its card first reached them and when their prompt
answered it; `intents`, from the owner's first prompt into a seat with none open to the
seat's done.

Offline: a sandbox HOME, the webhook post faked, no seat.
"""

from contextlib import closing
import sqlite3
import sys
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import history, notify

SEAT = "fix-api"


class OwnerRecord(Sandbox):
    def rows(self, table):
        with closing(sqlite3.connect(history.path())) as db:
            return db.execute(f"SELECT * FROM {table} ORDER BY 2").fetchall()

    def said(self, kind, text, at, event_id=None):
        with notify.session_lock(SEAT) as name:
            notify._said(name, kind, text, event_id=event_id, at=at)

    def event(self, kind, created_at, ident):
        return {"id": ident, "session": SEAT, "kind": kind, "text": "words", "files": [],
                "payload": {"username": "agentkit", "embeds": [{}]}, "message": "m",
                "created_at": created_at, "sink": notify.sink() is not None,
                "status": "pending", "attempts": 0, "next_attempt": 0}

    def test_a_question_an_alert_and_a_done_are_rows_dated_at_their_notices(self):
        self.said("needs", "Which schema?", 100.0)
        self.said("needs", "And the port?", 160.0)          # asked beside the standing one
        self.assertEqual(self.rows("notices"), [(SEAT, 100.0, "needs", None, None),
                                                (SEAT, 160.0, "needs", None, None)])
        notify.answered(SEAT, 200.0)                       # the owner's one prompt answers both
        self.assertEqual([row[4] for row in self.rows("notices")], [200.0, 200.0])
        self.said("done", "shipped", 300.0)
        self.said("needs", "gh login expired", 400.0, event_id="auth:gh")   # ak's own alert
        self.said("needs", "gh login expired", 400.0, event_id="auth:gh")   # said again: once
        self.assertEqual([(row[1], row[2]) for row in self.rows("notices")],
                         [(100.0, "needs"), (160.0, "needs"), (300.0, "done"), (400.0, "alert")])
        notify.answered(SEAT, 450.0)                       # an alert is nobody's question
        self.assertEqual([row[4] for row in self.rows("notices")], [200.0, 200.0, None, None])

    def test_a_delivered_card_pages_the_latest_notice_once(self):
        self.said("needs", "Which schema?", 100.0)

        def delivered(payload, files, message, receipt=None):
            receipt.update(status="delivered", message_id="m1", webhook="w")

        def pending(payload, files, message, receipt=None):
            receipt.update(status="pending", error="rate limited", retry_after=5)

        def attempt(event, post, now):
            # under the outbox lock, as the card queue and the tick's retry call it
            with patch.object(notify, "webhook", return_value="https://hooks.invalid/x"), \
                    patch.object(notify, "post", post), \
                    patch.object(notify.time, "time", return_value=now), notify.outbox_lock():
                self.assertEqual(notify._attempt(event), 0)

        attempt(self.event("needs", 150.0, "e1"), delivered, 170.0)
        self.assertEqual(self.rows("notices"), [(SEAT, 100.0, "needs", 170.0, None)])
        # a done card pages the done row, and a card that stays pending pages nothing
        self.said("done", "shipped", 300.0)
        self.said("needs", "Next?", 330.0)
        attempt(self.event("done", 310.0, "e2"), delivered, 320.0)
        attempt(self.event("needs", 335.0, "e3"), pending, 340.0)
        self.assertEqual(self.rows("notices"), [(SEAT, 100.0, "needs", 170.0, None),
                                                (SEAT, 300.0, "done", 320.0, None),
                                                (SEAT, 330.0, "needs", None, None)])

    def test_the_owner_s_prompt_begins_an_intent_and_the_seat_s_done_ends_it(self):
        notify.answered(SEAT, 50.0)          # the first message of a job: no question standing
        notify.answered(SEAT, 60.0)          # the same job
        self.assertEqual(self.rows("intents"), [(SEAT, 50.0, None)])
        self.said("done", "shipped", 300.0)
        self.assertEqual(self.rows("intents"), [(SEAT, 50.0, 300.0)])
        self.said("needs", "Next?", 310.0)
        notify.answered(SEAT, 400.0)         # answers the question and begins the next intent
        self.assertEqual(self.rows("intents"), [(SEAT, 50.0, 300.0), (SEAT, 400.0, None)])
        self.assertEqual(self.rows("notices")[-1][4], 400.0)
        self.said("done", "again", 500.0)
        self.said("done", "once more", 600.0)   # no intent open: nothing to end
        self.assertEqual(self.rows("intents"), [(SEAT, 50.0, 300.0), (SEAT, 400.0, 500.0)])


if __name__ == "__main__":
    unittest.main()
