"""A seat at rest with nothing running, asked or owed reads idle; one that owes work reads why.

The bottom of the ladder used to be `needs you · waiting for you` for every seat at its prompt:
a new seat, a conversation that ended, a plan it finished.  The owner's rule (14 Oct 2026): those
rest, `idle`.  A seat that stopped with a line of its plan still owed is the owner's, and the
reason names the line -- the same test the stop hook ends a turn on (`stop.owed_line`), so the
word and the turn's end never disagree.  Offline: a temporary HOME, no tmux.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, notify, stop, watch  # noqa: E402

SEAT = "acme-api"
OWED = "- [ ] the parser reads both schemas · check: `false` · acme · written 2026-10-14 09:00\n"


class IdleAtRest(Sandbox):
    def decide(self, live=None, records=()):
        found = watch.session_state(SEAT, now=10000, session={"name": SEAT}, records=list(records),
                                    live=live or {"state": "at_prompt", "began": 9000},
                                    harness="claude", auth_out={}, gh_out={}, token_out=None,
                                    previous={})
        return found["word"], found["reason"]

    def test_nothing_asked_or_owed_is_idle(self):
        self.assertEqual(self.decide(), ("idle", ""))

    def test_work_owed_and_nothing_running_is_the_owners_and_names_the_line(self):
        config.plan_path(SEAT).write_text(OWED)
        self.assertEqual(self.decide(),
                         ("needs you", "stopped with work open: the parser reads both schemas"))
        self.assertTrue(stop.owed(SEAT))

    def test_a_hand_kept_line_is_named_whatever_follows_its_box(self):
        config.plan_path(SEAT).write_text("- [ ]\tpreserve the export\n")
        self.assertEqual(self.decide(), ("needs you", "stopped with work open: preserve the export"))

    def test_a_question_kept_for_the_turns_end_is_no_rest(self):
        watch.seat_write(SEAT, unasked=[{"text": "Which schema?", "time": 9500}])
        self.assertEqual(self.decide()[0], "needs you")

    def test_a_question_on_its_screen_or_asked_is_still_the_owners(self):
        self.assertEqual(self.decide({"state": "asking", "evidence": "Allow the command?",
                                      "began": 9000}), ("needs you", "Allow the command?"))
        notify.record(SEAT, "needs", "Which schema should acme use?", time=9000)
        self.assertEqual(self.decide(), ("needs you", "Which schema should acme use?"))

    def test_a_done_a_run_of_its_own_then_failed_is_still_the_owners(self):
        """The card pass marks a done seen once a run of its own fails after it; the failure
        stays the owner's, at rest as anywhere."""
        failed = {"run_id": "r1", "launched_session": SEAT, "handed_back": True,
                  "state": "fail", "verdict": "FAIL", "started_at": 8000, "finished_at": 9500}
        notify.record(SEAT, "done", "all shipped", time=9000, seen=True)
        self.assertEqual(self.decide(records=[(Path("r1"), failed)]),
                         ("needs you", "run r1 failed; declaration dropped"))

if __name__ == "__main__":
    unittest.main()
