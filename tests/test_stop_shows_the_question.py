"""A turn that ends on a question to the owner shows it, as recorded, on the seat's screen.

A seat asked with `ak notify needs`, and the question was nowhere on its screen: the command's
own output is folded away, the bar shows a question's start, and a seat that asked early had
long scrolled past it.  So a stop that stands while that question is unanswered prints it as
`systemMessage`, which the harness draws under the turn's last message: on the turn that asked,
whose question is kept back until that end (tests/test_question_waits_for_the_stop.py), and on
every later one that ends before the answer.

hooks/orchestrator-stop.sh runs as the harness runs it, on its own JSON on stdin, against
invented records in a temporary HOME.  No real seat, harness or notification is touched.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT = "acme-question"
QUESTION = ("Which schema should acme use?\n"
            "1) v1 keeps the legacy fields the importer still reads.\n"
            "2) v2 drops them, and the parser is a third shorter. " + "Recommend v2. " * 40)


class StopShowsTheQuestion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-stop-shows-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.state.mkdir(parents=True)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                    "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}
        self.turn = time.time() - 60
        self.opened()

    def opened(self):
        """A prompt opened a turn a minute ago, as hooks/seat-state.sh writes it down."""
        (self.state / f"stop-{SEAT}.json").write_text(
            json.dumps({"session": SEAT, "turn": self.turn, "blocks": 0}))

    def kept(self):
        """The question as the seat's own command keeps it back mid-turn: in its record."""
        (self.state / f"seat-{SEAT}.json").write_text(json.dumps({
            "session": SEAT, "unasked": {"text": QUESTION, "at": self.turn + 30}}))

    def notice(self, kind="needs", when=None, **extra):
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps({
            "session": SEAT, "kind": kind, "text": QUESTION,
            "time": self.turn + 30 if when is None else when, **extra}))

    def stop(self, said="The schema is yours to pick.", **payload):
        done = subprocess.run(["bash", str(HOOK)], input=json.dumps({
            "hook_event_name": "Stop", "last_assistant_message": said, "background_tasks": [],
            **payload}), text=True, capture_output=True, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def test_the_turn_that_asked_ends_with_the_question_as_recorded(self):
        self.kept()
        self.assertEqual(self.stop(), {"systemMessage": QUESTION})

    def test_a_later_turn_that_ends_before_the_answer_shows_it_again(self):
        self.notice(when=self.turn - 3600)      # asked an hour before this turn, a hand-back's;
                                                # released since, so it stands
        self.assertEqual(self.stop("Parser merged."), {"systemMessage": QUESTION})

    def test_an_answered_question_is_shown_no_more(self):
        self.notice(when=self.turn - 3600, answered_at=self.turn)
        shown = self.stop("Using v2.")
        self.assertEqual(shown["decision"], "block")    # and this turn ended on nothing
        self.assertNotIn("systemMessage", shown)

    def test_a_stop_on_background_work_shows_it_too(self):
        """Its composer is open and the seat waits: the question is asked at that stop."""
        self.kept()
        self.assertEqual(self.stop(background_tasks=[{"type": "local_bash", "id": "b1"}]),
                         {"systemMessage": QUESTION})

    def test_a_stop_sent_back_to_work_shows_nothing(self):
        shown = self.stop("Let me know if I should continue.")
        self.assertEqual(shown["decision"], "block")
        self.assertNotIn("systemMessage", shown)

    def test_a_done_and_a_watchers_alert_are_no_question(self):
        self.notice(kind="done")
        self.assertIsNone(self.stop("All merged."))
        self.opened()
        self.notice(when=self.turn - 3600, watcher=True)
        self.assertNotIn("systemMessage", self.stop("Still building.") or {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
