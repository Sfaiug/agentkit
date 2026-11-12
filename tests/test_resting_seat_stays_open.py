"""A seat stays open until the owner closes it, and one an older ak put to sleep comes back on its
own conversation and takes what is owed it: the answer key in
tests/test_key_a_resting_seat_stays_open.py, run here.  Offline, on `test_handback`'s fake seat,
what is owed such a seat waits for it while it is not back yet, and nothing forgets it meanwhile."""

from contextlib import redirect_stdout
import io
import sys
import time
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_a_resting_seat_stays_open import RestingSeatStaysOpen
from test_handback import SEAT, HandBack
from fixtures.tick import only_passes
from agentkit import config, job as jobs, orch, watch


class SleptSeat(HandBack):
    """The seat as an older ak left it asleep: gone from tmux, marked asleep since its launch,
    last seen long ago.  Its first reopen fails, as a tmux with no server does."""

    def setUp(self):
        super().setUp()
        config.update_session(SEAT, launched=1, asleep=2, seen=1)
        self.resumes = []
        self.stack.enter_context(patch.object(orch, "resume", side_effect=self.resume))

    def resume(self, cfg, name, **_kw):
        self.resumes.append(name)
        if len(self.resumes) == 1:
            raise OSError("no server running")
        self.rows.append(self.live())
        config.update_session(name, launched=time.time())
        return "resumed"

    def test_the_menu_s_sweep_keeps_it_a_year_unseen(self):
        config.plan_path(SEAT).write_text("- [ ] the api\n")
        with patch.object(orch.time, "time", return_value=time.time() + 365 * 86400), \
                patch.object(orch, "session_absent", return_value=True), \
                patch.object(orch, "reconcile"), patch.object(orch, "sweep_finished"):
            orch.maintenance(self.logs.append)
        self.assertIn(SEAT, config.session_records())
        self.assertTrue(config.plan_path(SEAT).exists())

    def test_a_run_s_ending_waits_through_a_failed_reopen_and_is_typed_once(self):
        self.failed()
        for _ in range(3):
            with only_passes(self.root, "slept seats", "endings"), redirect_stdout(io.StringIO()):
                self.assertEqual(watch.main([]), 0)
        self.assertEqual(self.resumes, [SEAT, SEAT])
        self.assertEqual((len(self.typed), self.cards), (1, []))
        self.assertNotIn("asleep", config.session_records()[SEAT])

    def test_a_job_s_ending_waits_through_a_failed_reopen(self):
        for answer in ("busy", "busy", "sent"):
            self.assertEqual(jobs.job_hand_back(SEAT, "job done", self.logs.append), answer)
            watch.reopen_slept(self.cfg, self.logs.append)
        self.assertEqual(self.cards, [])

    def test_a_merge_s_health_notice_waits_for_it_not_for_another_seat(self):
        other = {**self.live(), "name": "other"}
        with patch.object(watch, "after_merge_fallback", return_value=other):
            self.assertIsNone(watch.after_merge_seat({"launched_session": SEAT}, "acme/api", {}))

    def test_a_maintainer_s_decision_waits_for_it_under_the_name_it_had_before_a_rename(self):
        config.rename_session(SEAT, "beta")
        url = "https://github.com/acme/api/pull/7"
        state = {"own": {url: {"session": SEAT, "decision": None, "done": False}}}
        with patch.object(watch, "pages", return_value=([], "")), \
                patch.object(watch, "gh_json", return_value=(
                    {"state": "CLOSED", "number": 7, "title": "Fix the api"}, "")):
            watch.outgoing(state, "acme", False, self.logs.append)
        self.assertFalse(state["own"][url]["done"], self.logs)
        self.assertEqual(self.typed, [])


def load_tests(loader, tests, pattern):
    """The key's tests and this file's own, not those `SleptSeat` inherits from `test_handback`."""
    suite = loader.loadTestsFromTestCase(RestingSeatStaysOpen)
    suite.addTests(SleptSeat(name) for name in loader.getTestCaseNames(SleptSeat)
                   if name in SleptSeat.__dict__)
    return suite


if __name__ == "__main__":
    unittest.main()
