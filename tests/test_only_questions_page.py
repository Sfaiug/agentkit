"""Only what the owner alone can clear pages them, besides the finished job.

A question (a dialog on the seat's screen, the seat's own `ak notify needs`, an outside pull
request's merge question) and a failure only the owner can fix (a login, a dying worker token,
a seat ak could not reopen with a run of its own going, ended or interrupted, a job whose seat is
gone) send a card once they have stood a minute; an alert asked beside a question standing
unanswered leaves it asking.  Every other `needs you` -- an idle prompt, a draft never sent, a run the seat can still
decide on, a seat that went and that ak reopens -- is on every screen and pages nobody; and a
job's own `all N tasks finished` is handed to its seat, which says done itself.  Offline: a
temporary HOME, a card sink, no tmux.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config, notify, orch, watch

SEAT = "acme-api"


class OnlyQuestionsPage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".pages-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        home = self.root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name,
                                                  home if name == "HOME" else home / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": SEAT, "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AK_NOTIFY_SINK": "off", "AK_RUN_ROLE": ""}, clear=False))
        config.ensure_dirs()
        self.posts = []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="disabled", message_id=str(len(self.posts)), webhook="sink")
            return 0

        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))

    def held(self, answer, seat=None):
        """The card pass as the word stands, and again once it has stood its minute."""
        for now in (1000, 1000 + notify.CARD_WAIT + 1):
            with patch.object(watch, "session_state", return_value=dict(answer, since=1000)):
                notify.transition(SEAT, dict(answer, since=1000), now=now, seat=seat)
        return self.posts

    def test_a_needs_you_nobody_asked_pages_nobody(self):
        for reason in ("waiting for you", "unsent: acme draft",
                       "run fix-api parked: its checks failed twice",
                       "session closed: press 3 to reopen"):
            with self.subTest(reason=reason):
                self.assertEqual(self.held({"word": "needs you", "reason": reason}), [])
                config.card_path(SEAT).unlink(missing_ok=True)

    def test_a_question_pages_once_its_minute_is_up(self):
        self.assertEqual(self.held({"word": "needs you", "reason": "Allow the command?",
                                    "page": True}), [f"Needs you · {SEAT}"])

    def test_a_question_after_one_that_went_pages_again(self):
        # the first dialog's card closes as the seat waits at its prompt, though the word
        # stays `needs you`; the next dialog is a question of its own, after its own minute
        dialog = {"word": "needs you", "reason": "Allow the command?", "page": True}
        with patch.object(notify, "installed_at", return_value=900):
            for now, answer in ((1000, dict(dialog, page_since=1000)),
                                (1061, dict(dialog, page_since=1000)),
                                (1100, {"word": "needs you", "reason": "waiting for you"}),
                                (1200, dict(dialog, page_since=1200)),
                                (1261, dict(dialog, page_since=1200))):
                with patch.object(watch, "session_state", return_value=dict(answer, since=1000)):
                    notify.transition(SEAT, dict(answer, since=1000), now=now)
        self.assertEqual(self.posts, [f"Needs you · {SEAT}"] * 2)

    def test_an_alert_beside_a_standing_question_still_asks_it(self):
        notify.record(SEAT, "needs", "Which schema should acme use?", time=990)
        with notify.session_lock(SEAT) as name:
            notify._said(name, "needs", "Run fix-api stalled.", event_id="stalled:fix-api:900")
        joined = notify.last(SEAT)
        self.assertIn("Which schema should acme use?", joined["text"])
        self.assertTrue(notify.pages(joined))

    def test_a_seat_ak_could_not_reopen_pages(self):
        for source in ("revive:acme-api:fix-api:900", "orphan:fix-api:800:900",
                       "recovery:fix-api:900", "job:acme-batch:900"):
            with self.subTest(source=source):
                self.posts.clear()
                config.card_path(SEAT).unlink(missing_ok=True)
                notify.record(SEAT, "needs", "Run fix-api is still going. agentkit could not "
                              "reopen the seat.", source=source, time=990)
                gone = {"name": SEAT, "exited": True}
                self.assertEqual(self.held({"word": "needs you",
                                            "reason": "session closed: press 3 to reopen"},
                                           seat=gone), [f"Needs you · {SEAT}"])

    def test_an_alert_its_seat_can_mend_does_not_page(self):
        notify.record(SEAT, "needs", "Run fix-api stalled: resume it with `ak run resume`.",
                      source="stalled:fix-api:900", time=990)
        self.assertEqual(self.held({"word": "needs you", "reason": "run fix-api stalled"}), [])

    def test_the_ladder_marks_only_what_he_alone_can_clear(self):
        def word(found=None, notice=None):
            config.notify_path(SEAT).unlink(missing_ok=True)
            if notice:
                notify.record(SEAT, "needs", notice[0], source=notice[1], time=990)
            return watch.session_state(SEAT, now=1000, session={"name": SEAT}, records=[],
                                       live=found or {}, harness="claude", auth_out={},
                                       gh_out={}, token_out=None, previous={})

        dialog = word({"state": "asking", "evidence": "Allow the command?", "began": 995})
        self.assertEqual((dialog["word"], dialog.get("page")), ("needs you", True))
        own = word(notice=("Which schema should acme use?", None))
        self.assertEqual((own["word"], own.get("page")), ("needs you", True))
        alert = word(notice=("Run fix-api stalled.", "stalled:fix-api:900"))
        self.assertFalse(alert.get("page"))
        idle = word({"state": "at_prompt", "began": 995})
        self.assertFalse(idle.get("page"))
        config.notify_path(SEAT).unlink(missing_ok=True)
        token = watch.session_state(SEAT, now=1000, session={"name": SEAT}, records=[], live={},
                                    harness="claude", auth_out={}, gh_out={}, previous={},
                                    token_out={"claude": {"harness": "claude", "at": 990,
                                                          "remedy": "replace it", "expired": True}})
        self.assertEqual((token["word"], token.get("page")), ("needs you", True))

    def test_a_jobs_own_finish_is_no_done_card(self):
        notify.record(SEAT, "done", "job acme-batch: all 3 tasks finished",
                      source="job:acme-batch:900", time=990)
        found = watch.session_state(SEAT, now=1000, session={"name": SEAT}, records=[],
                                    live={"state": "at_prompt", "began": 995}, harness="claude",
                                    auth_out={}, gh_out={}, token_out=None, previous={})
        self.assertNotEqual(found["word"], "done")


if __name__ == "__main__":
    unittest.main()
