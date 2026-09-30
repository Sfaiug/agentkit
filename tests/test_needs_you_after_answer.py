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


if __name__ == "__main__":
    unittest.main(verbosity=2)
