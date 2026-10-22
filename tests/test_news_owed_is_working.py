"""A seat at its prompt that ak still has a line to type into is working, never the owner's.

A seat ended its turn on `ak wait`; the run it waited on merged, and the tick could not type the
end of the wait in, because the owner's unsent text held the composer.  With its plan still
owing lines, the ladder's bottom read the seat as stopped with work open and paged the owner,
who was at that seat typing (19 Oct 2026).  The line ak owes the seat -- its wait's end or a run's
ending nobody heard -- is what moves it next, without the owner.  Offline: a temporary HOME, no
tmux.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, watch  # noqa: E402

SEAT = "acme-api"
OWED = "- [ ] the parser reads both schemas · check: `false` · acme · written 2026-10-14 09:00\n"
DRAFT = {"state": "draft", "authority": "screen", "evidence": "and add these posts", "began": 9000}
PROMPT = {"state": "at_prompt", "authority": "hook", "began": 9000}
# what `classify` offers when no hook fact and no screen rule said anything
UNREAD = {"state": "at_prompt", "authority": "", "rule": "none", "began": 9000}


class NewsOwedIsWorking(Sandbox):
    def setUp(self):
        super().setUp()
        config.plan_path(SEAT).write_text(OWED)

    def decide(self, live=DRAFT, records=()):
        found = watch.session_state(SEAT, now=10000, session={"name": SEAT}, records=list(records),
                                    live=dict(live), harness="claude", auth_out={}, gh_out={},
                                    token_out=None, previous={})
        return found["word"], found["reason"], found.get("unsent", "")

    def test_a_wait_over_and_not_yet_told_is_working(self):
        watch.seat_write(SEAT, wait={"on": "r7", "kind": "run", "at": 9000,
                                     "over": "run r7 ended PASS, merged"})
        self.assertEqual(self.decide(), (
            "working", "telling it its wait on r7 is over", "and add these posts"))
        self.assertEqual(self.decide(PROMPT)[0], "working")

    def test_an_ending_nobody_heard_is_working(self):
        merged = {"run_id": "r7", "launched_session": SEAT, "state": "pass", "verdict": "PASS",
                  "merged": True, "handback_pending": True, "started_at": 8000,
                  "finished_at": 9500}
        self.assertEqual(self.decide(records=[(Path("r7"), merged)]),
                         ("working", "telling it how run r7 ended", "and add these posts"))

    def test_a_screen_nobody_can_read_keeps_the_owners_word(self):
        watch.seat_write(SEAT, wait={"on": "r7", "kind": "run", "at": 9000,
                                     "over": "run r7 ended PASS, merged"})
        self.assertEqual(self.decide(UNREAD)[0], "needs you")
        watch.seat_write(SEAT, wait=None)
        unheard = {"run_id": "r7", "launched_session": SEAT, "state": "fail", "verdict": "FAIL",
                   "started_at": 8000, "finished_at": 9500}
        self.assertEqual(self.decide(UNREAD, records=[(Path("r7"), unheard)])[0], "needs you")

    def test_once_told_a_stop_with_work_open_is_the_owners_again(self):
        watch.seat_write(SEAT, wait={"on": "r7", "kind": "run", "at": 9000, "told": 9600,
                                     "over": "run r7 ended PASS, merged"})
        heard = {"run_id": "r7", "launched_session": SEAT, "state": "pass", "verdict": "PASS",
                 "merged": True, "handed_back": 9600, "started_at": 8000, "finished_at": 9500}
        self.assertEqual(self.decide(dict(PROMPT, began=9700), records=[(Path("r7"), heard)]),
                         ("needs you", "stopped with work open: the parser reads both schemas", ""))


if __name__ == "__main__":
    unittest.main()
