"""A seat whose turn is in flight reads working, even with a run of its own parked.

Rung 2b (a run of its own parked, so "needs you") used to come before rung 3 (a
turn in flight, so "working"): a seat mid-turn answering its owner read "needs
you", and every swing between the two sent a card. The turn outranks the parked
run now; a quiet prompt with the same run parked still reads "needs you" with
the parked line, and a question on its screen still reads "needs you" with the
question. Offline: a temporary HOME, fake run records and fake screen readings;
never a real seat, tmux or ~/.agentkit.
"""

import os
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, menu, run, watch

NOW = 1_800_000_000
SPENT = ("unfinished review; done-when and review are pending at round 4, but the round "
         "budget (3) is spent; split or re-scope the task")


class TurnBeforeParked(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")
        self.seat = {"name": "acme", "repo": self.repo, "path": self.repo,
                     "created": NOW - 5 * 86400, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        config.save_session(self.cfg, "acme", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})

    def receipt(self, name, **extra):
        """One undecided `exhausted` run of this seat's, stopped ten minutes ago."""
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        state = {"run_id": name, "title": f"Task {name}", "state": "exhausted", "verdict": None,
                 "launched_session": "acme", "reported": False, "repo": self.repo,
                 "executor": "opus", "reviewer": "astra", "rounds": 3, "round_summaries": [],
                 "finished_at": NOW - 600, "started_at": NOW - 3600, "error": SPENT, **extra}
        run.save_state(directory, state)
        return directory, state

    def decide(self, live, records):
        return watch.session_state("acme", NOW, session=self.seat, cfg=self.cfg,
                                   records=records, live=live, harness="claude",
                                   auth_out={}, gh_out={}, token_out={}, previous={})

    def test_turn_in_flight_with_parked_run_reads_working(self):
        directory, state = self.receipt("20260101-0900-spent")
        self.assertFalse(run.going(state, now=NOW))
        self.assertTrue(menu.v5o_needs_look(state, now=NOW))
        found = self.decide({"hooked": "working", "hooked_at": NOW - 60},
                            [(directory, state)])
        self.assertEqual((found["word"], found["reason"], found["since"]),
                         ("working", "", NOW - 60))

    def test_quiet_prompt_with_parked_run_reads_needs_you_with_the_parked_line(self):
        directory, state = self.receipt("20260101-0900-spent")
        found = self.decide({"state": "at_prompt", "began": NOW - 600}, [(directory, state)])
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], f"run {directory.name} parked: {SPENT}")
        self.assertEqual(found["since"], NOW - 600)

    def test_question_at_quiet_prompt_reads_needs_you_with_the_question_parked_or_not(self):
        directory, state = self.receipt("20260101-0900-spent")
        live = {"state": "asking", "evidence": "Which of the two schemas should it read?",
                "began": NOW - 120}
        for records in ([(directory, state)], []):
            with self.subTest(parked=bool(records)):
                found = self.decide(live, records)
                self.assertEqual((found["word"], found["reason"]),
                                 ("needs you", "Which of the two schemas should it read?"))


if __name__ == "__main__":
    unittest.main()
