"""A seat the owner closed rests; one that went on its own is the owner's only while it
owes work.

`x`, `ak orch stop` or a pause script closes a seat on purpose: nothing in it asks the owner
anything, so it reads `idle`, its number still the way back in.  A seat whose harness went on its
own (a crash, a host reboot) is the owner's while it owes work -- a line of its plan, a question
kept for its turn's end, a run of its own undecided -- since nothing moves it until it is opened;
with nothing owed it is `done` where its plan is finished, or rests.  Offline: a temporary HOME, no tmux.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, notify, orch, watch  # noqa: E402

SEAT = "acme-api"
OWED = "- [ ] the parser reads both schemas · check: `false` · acme · written 2026-10-14 09:00\n"


class ClosedSeatIdle(Sandbox):
    def decide(self, records=()):
        found = watch.session_state(SEAT, now=10000, session={"name": SEAT, "exited": True},
                                    number=3, records=list(records), live={}, harness=None,
                                    auth_out={}, gh_out={}, token_out=None, previous={})
        return found["word"], found["reason"]

    def test_closed_by_the_owner_rests(self):
        orch.mark_owner_closed(SEAT)
        config.plan_path(SEAT).write_text(OWED)        # even with work owed: the owner closed it
        self.assertEqual(self.decide(),
                         ("idle", "session closed by the owner: reopen it from past sessions"))

    def test_gone_on_its_own_owing_work_is_the_owners(self):
        config.plan_path(SEAT).write_text(OWED)
        self.assertEqual(self.decide(), ("needs you", "session closed: press 3 to reopen"))

    def test_gone_on_its_own_with_a_failure_nobody_decided_is_the_owners(self):
        # nobody was in the seat to take the run's ending back: its tally says `1 needs you`
        failed = {"state": "fail", "verdict": "FAIL", "launched_session": SEAT,
                  "finished_at": 9000}
        self.assertEqual(self.decide([(config.RUNS / "fix-api", failed)]),
                         ("needs you", "session closed: press 3 to reopen"))

    def test_gone_on_its_own_with_a_question_standing_is_the_owners(self):
        notify.record(SEAT, "needs", "Which schema?", time=9000)
        self.assertEqual(self.decide(), ("needs you", "session closed: press 3 to reopen"))

    def test_gone_on_its_own_owing_nothing_rests_or_says_done(self):
        self.assertEqual(self.decide(), ("idle", "session closed: press 3 to reopen"))
        config.plan_path(SEAT).write_text("- [x] Shipped.\n")
        self.assertEqual(self.decide()[0], "done")


if __name__ == "__main__":
    unittest.main()
