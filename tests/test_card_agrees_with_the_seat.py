"""A `Needs you` card that is out says what its seat says.

The owner got a card for a dialog, opened the seat to read it, and the card turned `Answered`
while the dialog was still up: any key in an attached terminal since the episode began closed
a card, sent or not.  Input in the seat still holds back a card that is not out yet -- he is
there.  One that is out stays `Needs you` for as long as its seat does, and reads `Answered`
once he answered or the seat needs him no more.
Offline: fake tmux and card delivery, and a temporary HOME.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config, notify, orch, watch

DIALOG = "Claude needs your permission"


class CardAgreesWithTheSeat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".card-agrees-")
        self.root = Path(self.tmp.name)
        home = self.root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.tmp.cleanup)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name,
                                                  home if name == "HOME" else home / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "seat", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_NOTIFY_SINK": "off", "AK_RUN_ROLE": ""}, clear=False))
        config.ensure_dirs()
        self.posts, self.closed = [], []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0

        def close_needs(previous, status):
            self.closed.extend(status for _ in previous.get("open_needs") or ())
            return []
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=close_needs))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.client = (0, "")       # what tmux says of the seat's clients: name, last input
        self.stack.enter_context(patch.object(orch, "tmux_out",
                                              side_effect=lambda *_a, **_k: self.client))

    def says(self, word, since, now, reason=DIALOG):
        """One tick's look at the seat: the word it reads, and the card pass after it."""
        answer = {"word": word, "since": since, "reason": reason}
        with patch.object(watch, "session_state", return_value=answer):
            notify.transition("seat", now=now)
        return json.loads(config.card_path("seat").read_text())

    def test_opening_the_seat_leaves_a_sent_card_as_it_is(self):
        self.assertTrue(self.says("needs you", 100, now=160)["sent"])   # a dialog, a minute up
        self.client = (0, "seat\t170")          # he switched in and pressed keys there
        for now in (180, 360, 3600):
            self.assertNotIn("closed", self.says("needs you", 100, now=now))
        self.assertEqual((self.posts, self.closed), (["Needs you · seat"], []))

    def test_it_reads_answered_once_the_seat_needs_him_no_more(self):
        self.says("needs you", 100, now=160)
        self.client = (0, "seat\t170")
        self.says("needs you", 100, now=180)
        self.says("working", 200, now=360, reason="")       # the dialog came down
        self.assertEqual(self.closed, ["Answered"])

    def test_his_prompt_closes_it_while_the_seat_still_reads_needs_you(self):
        self.says("needs you", 100, now=160, reason="waiting for you")
        notify.answered("seat", 170)            # the harness's prompt hook, before any tick
        self.says("needs you", 100, now=180, reason="waiting for you")
        self.assertEqual(self.closed, ["Answered"])

    def test_input_in_the_seat_still_holds_back_a_card_that_is_not_out(self):
        self.client = (0, "seat\t130")          # he is in the seat as the dialog goes up
        for now in (160, 360):
            self.says("needs you", 100, now=now)
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
