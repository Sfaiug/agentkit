"""A card that is out reads `Answered` once nothing the owner alone can clear stands.

The word may stay `needs you` after a dialog comes down -- the seat waits at its prompt -- but
nothing asks the owner any more, so the card says so, and the next question is carded as its
own minute ends; a login that comes up under the same word waits its own minute.  An alert
asked beside a question standing unanswered keeps asking it.  Offline: a temporary HOME, a card
sink, no tmux.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import notify, orch, watch  # noqa: E402

SEAT = "acme-api"


class CardCloses(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off", "AK_RUN_ROLE": ""}))
        self.posts, self.closed = [], []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0

        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", side_effect=lambda card,
                                              status: self.closed.append(status) or 0))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(notify, "installed_at", return_value=900))

    def test_a_question_after_one_that_went_pages_again(self):
        dialog = {"word": "needs you", "reason": "Allow the command?", "page": True}
        for now, answer in ((1000, dict(dialog, page_since=1000)),
                            (1061, dict(dialog, page_since=1000)),
                            (1100, {"word": "needs you", "reason": "waiting for you"}),
                            (1200, dict(dialog, page_since=1200)),
                            (1261, dict(dialog, page_since=1200))):
            with patch.object(watch, "session_state", return_value=dict(answer, since=1000)):
                notify.transition(SEAT, dict(answer, since=1000), now=now)
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"] * 2)
        self.assertEqual(self.closed[:1], ["Answered"])

    def test_a_login_after_a_question_that_went_waits_its_own_minute(self):
        real, tokens = watch.session_state, {}
        live = {"state": "asking", "evidence": "Allow the command?", "began": 1000}

        def state(*args, **kwargs):
            return real(*args, **kwargs, live=live, harness="claude", auth_out={}, gh_out={},
                        token_out=tokens)

        with patch.object(watch, "session_state", side_effect=state):
            for now in (1000, 1061):
                notify.transition(SEAT, now=now, seat={"name": SEAT})
            live.update(state="at_prompt", evidence="", began=1100)
            notify.transition(SEAT, now=1100, seat={"name": SEAT})
            tokens["claude"] = {"harness": "claude", "remedy": "replace it", "expired": True,
                                "at": 1200}
            for now in (1200, 1259):
                notify.transition(SEAT, now=now, seat={"name": SEAT})
            self.assertEqual(len(self.posts), 1)
            notify.transition(SEAT, now=1261, seat={"name": SEAT})
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"] * 2)

    def test_an_alert_beside_a_standing_question_still_asks_it(self):
        notify.record(SEAT, "needs", "Which schema should acme use?", time=990)
        with notify.session_lock(SEAT) as name:
            notify._said(name, "needs", "Run fix-api stalled.", event_id="stalled:fix-api:900")
        joined = notify.last(SEAT)
        self.assertIn("Which schema should acme use?", joined["text"])
        self.assertTrue(notify.pages(joined))


if __name__ == "__main__":
    unittest.main()
