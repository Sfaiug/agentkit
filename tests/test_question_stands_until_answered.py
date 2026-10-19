"""A seat's own question stands until its owner answers it.

A seat asks with `ak notify needs` and works on what does not wait for the answer, so its
screen moves and shows no question.  Its owner switching into it, or opening it from the menu
and watching it work, answers nothing: the Discord card stays `Needs you`, and the row stays
`needs you`, until his prompt (`notify.answered`, which the harness's prompt hook reports).
Where a harness reports no prompts, output after an open is still the only answer there is,
as it is for a watcher's alert.  A watcher's alert -- a login, a stuck seat -- leaves the seat's
open question in place: taking its place, the question was gone once the alert was retracted.
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


class QuestionStands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".question-stands-")
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
        self.posts = []

        def post(payload, files, message, receipt):
            self.posts.append(payload)
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "terminal_notice"))
        self.client = (0, "")
        self.stack.enter_context(patch.object(orch, "tmux_out",
                                              side_effect=lambda *_a, **_k: self.client))

    def needs_you(self, now, since=100):
        notify.transition("seat", {"word": "needs you", "since": since, "reason": "question"},
                          now=now)

    def card(self):
        return json.loads(config.card_path("seat").read_text())

    def sent_card(self, **notice):
        """A needs you since 100 whose card went out at 160, the seat's question standing."""
        if notice:
            notify.record("seat", "needs", "Ship the acme parser today?", time=100, **notice)
        self.needs_you(now=160)
        self.assertEqual(len(self.posts), 1)
        self.assertTrue(self.card()["sent"])

    def test_switching_into_the_seat_leaves_its_question_open(self):
        self.sent_card(watcher=False)
        episode = self.card()["episode"]
        self.client = (0, "seat\t170")      # he switched in and pressed keys there
        for now in (180, 240, 600):
            self.needs_you(now=now)
        self.assertEqual(self.card()["episode"], episode)
        self.assertFalse(notify.resolved(notify.last("seat")))
        notify.answered("seat", 650)          # his prompt
        self.needs_you(now=660)
        self.assertNotEqual(self.card()["episode"], episode)
        self.assertEqual(len(self.posts), 1)

    def test_a_watchers_alert_leaves_an_open_question_standing(self):
        question, alert = "Ship the acme parser today?", "seat needs login"
        self.assertEqual(notify.shaped("needs", question, session="seat"), 0)
        self.assertEqual(notify.shaped("needs", alert, session="seat",
                                       event_id="auth:seat:claude:1"), 0)
        self.assertEqual(notify.last("seat")["text"], question)
        notify.clear("seat", notice=alert)          # the login came back
        self.assertTrue(watch.owner_question(notify.last("seat")))
        self.assertEqual(notify.last("seat")["text"], question)

    def test_switching_in_leaves_a_watchers_alert_and_a_dialogs_card_open_too(self):
        """A card that is out says what its seat says (tests/test_card_agrees_with_the_seat.py):
        while the seat reads `needs you`, his keys there close none of them."""
        for notice in ({"watcher": True}, {}):      # {}: a dialog on its screen, no notice
            with self.subTest(notice=notice):
                self.setUp()
                if not notice:
                    self.stack.enter_context(patch.object(watch, "session_state", side_effect=(
                        lambda *_a, **_k: {"word": "needs you", "since": 100, "page": True,
                                           "reason": "Allow the command?"})))
                self.sent_card(**notice)
                episode = self.card()["episode"]
                self.client = (0, "seat\t170")
                self.needs_you(now=180)
                self.assertEqual(self.card()["episode"], episode)

    def test_output_after_an_open_answers_nothing_where_prompts_are_reported(self):
        notify.record("seat", "needs", "Ship the acme parser today?", time=100)
        notify.opened("seat", lambda: "Reading the parser")
        self.assertFalse(notify.progress("seat", lambda: "Writing the tests", "claude"))
        self.assertEqual(notify.last("seat")["text"], "Ship the acme parser today?")

    def test_output_after_an_open_is_the_answer_where_no_prompt_is_reported(self):
        notify.record("seat", "needs", "Ship the acme parser today?", time=100)
        notify.opened("seat", lambda: "Reading the parser")
        self.assertTrue(notify.progress("seat", lambda: "Shipping the parser", "muse"))
        self.assertIsNone(notify.last("seat"))

    def test_a_watchers_alert_is_still_answered_by_output(self):
        notify.record("seat", "needs", "seat looks stuck", time=100, watcher=True)
        notify.opened("seat", lambda: "Reading the parser")
        self.assertTrue(notify.progress("seat", lambda: "Writing the tests", "claude"))
        self.assertIsNone(notify.last("seat"))


if __name__ == "__main__":
    unittest.main()
