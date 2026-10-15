"""Only what the owner alone can clear pages them, besides the finished job.

A question, or a failure only the owner can fix, sends a card once it has stood a minute; an
idle prompt, a draft never sent, a run the seat can still decide on or a seat ak reopens pages
nobody.  Offline: a temporary HOME, a card sink, no tmux.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, handback, notify, orch, watch  # noqa: E402

SEAT = "acme-api"


class OnlyQuestionsPage(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_NOTIFY_SINK": "off", "AK_RUN_ROLE": ""}))
        self.posts = []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0

        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))

    def held(self, reason, page=False, seat=None, source=None):
        """The posts once that `needs you` has stood its minute, from a fresh card."""
        config.card_path(SEAT).unlink(missing_ok=True)
        self.posts.clear()
        if source:
            notify.record(SEAT, "needs", reason, source=source, time=990)
        answer = {"word": "needs you", "reason": reason, "since": 1000, "page": page}
        for now in (1000, 1000 + notify.CARD_WAIT + 1):
            with patch.object(watch, "session_state", return_value=answer):
                notify.transition(SEAT, answer, now=now, seat=seat)
        return self.posts

    def test_a_question_or_what_only_the_owner_can_mend_pages_and_nothing_else(self):
        for reason in ("waiting for you", "unsent: acme draft",
                       "run fix-api parked: its checks failed twice",
                       "session closed: press 3 to reopen"):
            self.assertEqual(self.held(reason), [], reason)
        self.assertEqual(self.held("Allow the command?", page=True), [f"Needs you · {SEAT}"])
        gone = {"name": SEAT, "exited": True}
        for source in ("revive:acme-api:fix-api:900", "orphan:fix-api:800:900",
                       "recovery:fix-api:900", "job:acme-batch:900"):
            self.assertEqual(self.held("agentkit could not reopen the seat.", seat=gone,
                                       source=source), [f"Needs you · {SEAT}"], source)
        # ... and a seat stuck an hour that ak gave up typing into
        for source in ("stuck:acme-api:900", "stall:acme-api:900"):
            self.assertEqual(self.held("acme-api is stuck with no progress for an hour.",
                                       source=source), [f"Needs you · {SEAT}"], source)
        self.assertEqual(self.held("Run fix-api stalled.", source="stalled:fix-api:900"), [])

    def test_a_question_still_pages_with_a_parked_run_said_beside_it(self):
        notify.record(SEAT, "needs", "Which schema should acme use?", time=990)
        with patch.object(handback, "launcher_watched", return_value=True), \
                patch.object(watch, "type_into", return_value=False), \
                patch.object(notify, "transition", return_value=0):
            self.assertTrue(watch.tell_parked("fix-api", "review", SEAT, print))
        self.assertTrue(notify.pages(notify.last(SEAT)))

    def test_the_ladder_marks_only_what_the_owner_alone_can_clear(self):
        def page(found=None, notice=None, token=None, seat=None, records=()):
            config.notify_path(SEAT).unlink(missing_ok=True)
            if notice:
                notify.record(SEAT, "needs", notice[0], source=notice[1], time=990)
            answer = watch.session_state(SEAT, now=1000, session=seat or {"name": SEAT},
                                         records=list(records), number=1, live=found or {},
                                         harness="claude", auth_out={}, gh_out={},
                                         token_out=token, previous={})
            return answer["word"], bool(answer.get("page"))

        asked = ("needs you", True)
        self.assertEqual(page({"state": "asking", "evidence": "Allow?", "began": 995}), asked)
        self.assertEqual(page(notice=("Which schema should acme use?", None)), asked)
        self.assertEqual(page(token={"claude": {"harness": "claude", "at": 990,
                                                "remedy": "replace it", "expired": True}}), asked)
        self.assertFalse(page(notice=("Run fix-api stalled.", "stalled:fix-api:900"))[1])
        self.assertFalse(page({"state": "at_prompt", "began": 995})[1])
        # A run parked on a seat that went has nothing left to move it but the owner.
        gone = {"name": SEAT, "exited": True}
        stalled = [(config.RUNS / "fix-api", {"state": "stalled", "launched_session": SEAT,
                                               "started_at": 900})]
        self.assertEqual(page(seat=gone, records=stalled), asked)
        self.assertEqual(page(seat=gone), ("needs you", False))


if __name__ == "__main__":
    unittest.main()
