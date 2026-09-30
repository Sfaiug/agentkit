"""The owner's answer closes only the `needs you` it answered.

A seat back in `needs you` before the next tick -- a dialog, or waiting for the owner with no
new notice -- needs the owner again, and gets a card for it, though no tick saw it work in between.
Offline: fake tmux and card delivery, and a temporary HOME.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config, notify, orch, watch

SEAT = "fix-api"
QUESTION = "Which schema should acme use?"


class NeedsYouAfterAnswer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".needs-after-answer-")
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name) / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name,
                                                  home if name == "HOME" else home / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": tmp.name, "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_NOTIFY_SINK": "off", "AK_RUN_ROLE": ""}))
        config.ensure_dirs()
        self.cards, self.edits = [], []

        def post(payload, files, message, receipt):
            self.cards.append(message)
            receipt.update(status="disabled", message_id=str(len(self.cards)), webhook="sink")
            return 0

        def close(card, status):
            self.edits.extend((sent["message_id"], status) for sent in card.get("open_needs", []))
            return []

        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=close))
        # No client is attached to the seat's fake server.
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))

    def tick(self, now, reason):
        """The watch tick's own pass, with only the seat's screen made up: it reads `needs you`."""
        with patch.object(watch, "_session_state", return_value={
                "word": "needs you", "reason": reason, "since": 100}):
            self.assertEqual(notify.transition(SEAT, now=now, seat={"name": SEAT}), 0)

    def ask(self, at, question, since=100, event_id=None):
        """`ak notify needs` at `at`, with the seat's screen in `needs you` since `since`."""
        with patch.object(notify.time, "time", return_value=at), \
                patch.object(watch, "_session_state", return_value={
                    "word": "needs you", "reason": question, "since": since}):
            self.assertEqual(notify.shaped("needs", question, session=SEAT, event_id=event_id), 0)

    def back_in_needs_you(self, reason):
        notify.record(SEAT, "needs", QUESTION, time=100)
        self.tick(100, QUESTION)
        self.tick(160, QUESTION)
        self.assertEqual(self.cards, [f"Needs you · {SEAT}: {QUESTION}"])
        # The owner answers; the seat works and needs the owner again before the next tick.
        notify.answered(SEAT, 200)
        for now in (230, 300, 400, 500):
            self.tick(now, reason)
        self.assertEqual(self.edits, [("1", "Answered")])
        self.assertEqual(self.cards, [f"Needs you · {SEAT}: {QUESTION}",
                                      f"Needs you · {SEAT}: {reason}"])

    def test_waiting_for_the_owner_again_is_carded(self):
        self.back_in_needs_you("waiting for you")

    def test_a_dialog_after_the_answer_is_carded(self):
        self.back_in_needs_you("Allow the command?")

    def test_an_answer_typed_in_the_seat_still_cards_the_next_needs_you(self):
        notify.record(SEAT, "needs", QUESTION, time=100)
        self.tick(100, QUESTION)
        # The owner types the answer in an attached client across a tick, which ends that episode.
        with patch.object(orch, "tmux_out", return_value=(0, f"{SEAT}\t150")):
            self.tick(160, QUESTION)
        notify.answered(SEAT, 200)
        for now in (230, 300, 400, 500):
            self.tick(now, "waiting for you")
        self.assertEqual(self.cards, [f"Needs you · {SEAT}: waiting for you"])

    def test_an_edit_discord_did_not_take_is_tried_again_first(self):
        edit, refused = notify.close_needs.side_effect, []

        def close(card, status):
            if len(refused) < 2:
                refused.append(status)
                return list(card.get("open_needs", []))
            return edit(card, status)

        notify.close_needs.side_effect = close
        self.back_in_needs_you("waiting for you")

    def test_a_new_question_before_the_tick_keeps_the_answer(self):
        notify.record(SEAT, "needs", QUESTION, time=100)
        self.tick(100, QUESTION)
        self.tick(160, QUESTION)
        notify.answered(SEAT, 200)
        # The seat asks again with `ak notify` before any tick has read the answer.
        self.ask(220, "Which port?")
        for now in (300, 400, 500, 600):
            self.tick(now, "Which port?")
        self.assertEqual(self.edits, [("1", "Answered")])
        self.assertEqual(self.cards, [f"Needs you · {SEAT}: {QUESTION}",
                                      f"Needs you · {SEAT}: Which port?"])

    def test_a_new_question_after_an_upgrade_is_carded(self):
        notify.record(SEAT, "needs", QUESTION, time=100)
        self.tick(100, QUESTION)
        notify.answered(SEAT, 120)
        # This agentkit is installed at 150, and the seat asks again after it.
        with patch.object(notify, "installed_at", return_value=150):
            self.ask(220, "Which port?")
            for now in (300, 400, 500, 600):
                self.tick(now, "Which port?")
        self.assertEqual(self.cards, [f"Needs you · {SEAT}: Which port?"])

    def test_a_watcher_notice_after_an_upgrade_is_still_history(self):
        notify.record(SEAT, "needs", QUESTION, time=100)
        self.tick(100, QUESTION)
        notify.answered(SEAT, 120)
        # The watcher records a login that expired before this agentkit was installed at 150.
        with patch.object(notify, "installed_at", return_value=150):
            self.ask(220, "Login expired", event_id=f"auth:{SEAT}:claude:130")
            for now in (300, 400, 500, 600):
                self.tick(now, "Login expired")
        self.assertEqual(self.cards, [])

    def test_a_late_card_for_a_retired_question_reads_answered(self):
        notify.record(SEAT, "needs", QUESTION, time=100)
        self.tick(100, QUESTION)
        self.tick(160, QUESTION)
        notify.answered(SEAT, 200)
        with patch.object(watch, "_session_state", return_value={
                "word": "working", "reason": "", "since": 210}):
            notify.transition(SEAT, now=210, seat={"name": SEAT})
        # Discord is down when the seat asks again, and the question is retired before it is up.
        deliver = notify.post.side_effect
        notify.post.side_effect = lambda payload, files, message, receipt: receipt.update(
            status="pending") or 0
        self.ask(220, "Which port?", since=220)
        notify.clear(SEAT)
        notify.post.side_effect = deliver
        with patch.object(notify.time, "time", return_value=300 + notify.RETRY_BACKOFF[0]):
            notify.retry_pending(log=lambda _: None)
        self.assertEqual(self.edits, [("1", "Answered"), ("2", "Answered")])

    def test_a_needs_you_standing_before_an_upgrade_is_history(self):
        notify.record(SEAT, "needs", QUESTION, time=100)
        self.tick(100, QUESTION)
        self.tick(160, QUESTION)
        notify.answered(SEAT, 200)
        self.tick(230, "waiting for you")
        # This agentkit is installed while the seat still waits, from before the upgrade.
        with patch.object(notify, "installed_at", return_value=1000):
            for now in (1100, 1200, 1300, 1400):
                self.tick(now, "waiting for you")
        self.assertEqual(self.cards, [f"Needs you · {SEAT}: {QUESTION}"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
