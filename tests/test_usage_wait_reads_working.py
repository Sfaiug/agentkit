"""A seat whose subscription ran out reads working until ak resumes it, and pages nobody.

The owner's call (14 Oct 2026): a spent usage window is no question for him -- ak resumes the
seat when the usage comes back, or on another account sooner -- so the seat reads `working`,
its reason saying until when.  A harness upgrade does not wait for such a seat: no turn of it
is in flight, so text the owner typed and never sent joins its reason.  A move to another
account that failed is no wait that ends by itself, and stays his whatever its runs or `ak wait`
do.  Offline: a temporary HOME, no tmux.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, orch, update, watch  # noqa: E402

SEAT = "acme-api"
SPENT = "anthropic out of usage until 2026-10-15 20:00"


class UsageWaitReadsWorking(Sandbox):
    def decide(self, live=None, records=()):
        found = watch.session_state(SEAT, now=10000, session={"name": SEAT}, records=list(records),
                                    live=live or {"state": "at_prompt", "began": 9000},
                                    harness="claude", auth_out={}, gh_out={}, token_out=None,
                                    previous={})
        return found

    def test_a_spent_window_reads_working_until_it_comes_back(self):
        watch.seat_write(SEAT, usage_wait={"reason": SPENT, "until": 90000, "since": 9500})
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]), ("working", SPENT))
        self.assertEqual(found["resumes_at"], 90000)

    def test_its_screen_cannot_say_a_turn_is_in_flight(self):
        # the harness's refusal leaves a screen a turn could have drawn; the wait is the fact
        watch.seat_write(SEAT, usage_wait={"reason": SPENT, "until": 90000, "since": 9500})
        self.assertEqual(self.decide({"state": "working", "began": 9000})["reason"], SPENT)

    def test_an_unsent_draft_under_the_refused_turn_joins_its_reason(self):
        # the refused turn's UserPromptSubmit has no Stop: its hook still says working
        watch.seat_write(SEAT, usage_wait={"reason": SPENT, "until": 90000, "since": 9500})
        found = self.decide({"state": "draft", "evidence": "Fix the login redirect",
                             "began": 9000, "hooked": "working", "hooked_at": 9000})
        self.assertEqual((found["word"], found["reason"]),
                         ("working", f"{SPENT} · unsent: Fix the login redirect"))

    def test_a_failed_move_to_another_account_is_his(self):
        failed = "anthropic account reopen failed: no such file"
        watch.seat_write(SEAT, usage_wait={"reason": failed, "since": 9500})
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]), ("needs you", failed))
        run = (config.RUNS / "acme-run", {"state": "running", "title": "Build endpoint",
                                          "launched_session": SEAT, "started_at": 9940})
        found = self.decide(records=[run])
        self.assertEqual((found["word"], found["reason"]), ("needs you", failed))
        watch.seat_write(SEAT, wait={"on": "https://github.com/acme/api/pull/1", "kind": "pr",
                                     "at": 9940})
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]), ("needs you", failed))

    def test_an_upgrade_waits_for_turns_but_not_for_a_usage_wait(self):
        answers = {"waits": {"word": "working", "reason": SPENT, "resumes_at": 90000},
                   "busy": {"word": "working", "reason": "turn running"}}
        with patch.object(orch, "listing", return_value=[{"name": "waits"}, {"name": "busy"}]), \
                patch.object(watch, "session_state",
                             side_effect=lambda name, **_kw: answers[name]):
            self.assertEqual(update.working_sessions({"providers": {}}), ["busy"])


if __name__ == "__main__":
    unittest.main()
