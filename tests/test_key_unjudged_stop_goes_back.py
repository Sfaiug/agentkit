"""A seat at its prompt owing a line, on a stop no hook judged, is sent back by ak; it reads
`needs you` only once that did nothing.

A Claude seat's stop hook judges every stop it sees, so a seat at its prompt with an open line
is one it never saw, as a reopened conversation has, or let stand on a reason since gone, as a
run going that has merged.  Nobody has sent that seat back: until the tick has it reads
`working`, the tick types `continue` once for the words on its screen, and if those words still
stand it is the owner's.  A stop the hook asked the owner about, a question, a turn the owner
stopped, text in its composer and a seat with no plan stay as they are.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, its tick boxed, before seats of
tests/fixtures/akseat.py whose hooks fire as Claude fires them (tests/fixtures/hookdrive.py).
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, hookdrive
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

LINE = "The work is done"       # the words of tests/fixtures/akseat.py's PLAN_LINE
LAST = "I cannot reach the acme database from here."
ASKED = "Which database should acme use? Options: postgres (Recommended), sqlite."
RUN = "20261030-0900-fix-api"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class UnjudgedStopGoesBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus"])
        cls.hooks = hookdrive.Hooks(cls.home)

    def reopened(self, name, planned=True):
        """A seat just reopened on its conversation: at its prompt, its last hook SessionStart."""
        seat = Seat(self.home, name, planned=planned)
        fired = self.hooks.fire("SessionStart", {"source": "resume"}, seat=name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        return seat

    def turn(self, name):
        """A seat the owner has just given a turn, its plan's line open."""
        seat = Seat(self.home, name, screen="claude-working-pane.txt", planned=True)
        self.hooks.prompt("Build the acme parser.", seat)
        return seat

    def stops(self, seat, count, closing=LAST):
        """Fire `count` Stops of one turn closing on `closing`: whether each was sent back."""
        seat.show("claude-prompt-pane.txt")
        chat = hookdrive.transcript(self.home, seat.name, closing)
        back = []
        for n in range(count):
            fired = self.hooks.fire("Stop", {"background_tasks": [], "stop_hook_active": n > 0,
                                             "transcript_path": chat}, seat=seat.name, pane=seat)
            self.assertEqual(fired.code, 0, fired.err)
            back.append(any(out.get("decision") == "block" for out in fired.said))
        return back

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def why(self, name):
        """`ak orch why NAME`: its word, and the reason under it."""
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        return (done.out.splitlines()[0].removeprefix(name).strip(),
                done.out.partition("reason:")[2].partition("\n")[0].strip())

    def untouched(self, seat):
        """What that seat reads (`why`) after a tick that typed nothing into it."""
        self.tick()
        time.sleep(0.5)     # keys reach the pane a moment after tmux takes them
        self.assertEqual(seat.lines(), [])
        return self.why(seat.name)

    def test_a_reopened_seat_goes_back_once_then_is_the_owners(self):
        seat = self.reopened("reopened")
        self.assertEqual(self.why("reopened"),
                         ("working", f"going back to its open work: {LINE}"))
        self.tick()
        self.assertEqual(seat.wait_lines(1), ["continue"])
        self.tick()
        time.sleep(0.5)
        self.assertEqual(seat.lines(), ["continue"])
        self.assertEqual(self.why("reopened"), ("needs you", f"stopped with work open: {LINE}"))

    def test_a_stop_that_stood_on_a_run_since_merged_goes_back(self):
        now = time.time()
        path = f".agentkit/runs/{RUN}/run.json"
        run = {"run_id": RUN, "title": "fix-api", "launched_session": "merged",
               "started_at": now - 900}
        self.home.write(path, {**run, "state": "waiting", "waiting_on": {"line": "acme/api"}})
        seat = self.turn("merged")
        self.assertEqual(self.stops(seat, 1, closing="The fix is on its way."), [False])
        self.home.write(path, {**run, "state": "pass", "verdict": "PASS", "merged": True,
                               "finished_at": now - 60, "handed_back": now - 60})
        self.tick()
        self.assertEqual(seat.wait_lines(1), ["continue"])

    def test_a_stop_the_hook_asked_the_owner_about_is_not_typed_at(self):
        seat = self.turn("asked")
        self.assertEqual(self.stops(seat, 3), [True, True, False])
        word, reason = self.untouched(seat)
        self.assertEqual(word, "needs you")
        self.assertIn(LAST, reason)

    # The owner's composer is never the question's display. [21 Oct 2026]
    def test_a_recorded_question_is_not_typed_at(self):
        seat = self.turn("question")
        done = self.home.ak("notify", "needs", ASKED, env={"AGENTKIT_SESSION": "question"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.stops(seat, 1, closing=ASKED), [False])
        word, reason = self.untouched(seat)
        self.assertEqual(word, "needs you")
        self.assertIn("Which database should acme use?", reason)

    def test_a_turn_the_owner_stopped_rests(self):
        seat = self.turn("stopped")
        seat.show("claude-interrupted-pane.txt")
        self.hooks.interrupt(seat)
        self.assertEqual(self.untouched(seat)[0], "idle")

    def test_text_in_its_composer_is_left_as_it_was(self):
        seat = Seat(self.home, "drafting", screen="claude-multiline-draft-pane.txt", planned=True)
        self.assertEqual(self.untouched(seat), ("needs you", f"stopped with work open: {LINE}"))

    def test_a_seat_with_no_plan_rests(self):
        self.assertEqual(self.untouched(self.reopened("planless", planned=False))[0], "idle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
