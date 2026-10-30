"""Open plan work at a stop goes back twice, then the owner is asked with the seat's last words.

A Claude seat whose plan has an open line and whose turn ends with nothing recorded has its Stop
sent back with the harness's block decision, at most twice in one turn.  The third stands: the
seat reads `needs you`, its question to the owner holding its last words, and once that has
stood a minute the owner is paged, the outbox's record of that page holding them too: what the
sink is sent names only the seat (tests/test_key_page_question_once.py).  A new prompt counts
afresh.  A plan with no open line, a question asked with `ak notify needs`, or an `ak wait` on a
run of its own still going lets the first Stop stand.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, its tick boxed, before seats of
tests/fixtures/akseat.py whose hooks fire as Claude fires them (tests/fixtures/hookdrive.py),
paging tests/fixtures/sink.py.
"""

import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, hookdrive
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.sink import Sink
from test_key_notify_needs_card import events

LAST = "I cannot reach the acme database from here."
ASKED = "Which database should acme use? Options: postgres (Recommended), sqlite."
RUN = "20261030-0900-fix-api"
MINUTE = 60


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class OpenWorkSentBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        akconfig.write(cls.home, ["opus"])
        cls.hooks = hookdrive.Hooks(cls.home)

    def turn(self, name, planned=True):
        """A seat the owner has just given a turn, its plan's line open unless `planned` is
        False."""
        seat = Seat(self.home, name, screen="claude-working-pane.txt", planned=planned)
        self.hooks.prompt("Build the acme parser.", seat)
        return seat

    def stops(self, seat, count, closing=LAST):
        """What each of `count` Stops in one turn closing on `closing` sent back: the reason it
        blocked with, None where it stood.  Past a block, Claude goes on and marks its next."""
        seat.show("claude-prompt-pane.txt")
        chat = hookdrive.transcript(self.home, seat.name, closing)
        back = []
        for n in range(count):
            fired = self.hooks.fire("Stop", {"background_tasks": [], "stop_hook_active": n > 0,
                                             "transcript_path": chat}, seat=seat.name, pane=seat)
            self.assertEqual(fired.code, 0, fired.err)
            blocks = [out for out in fired.said if out.get("decision") == "block"]
            self.assertTrue(all(isinstance(out.get("reason"), str) and out["reason"].strip()
                                for out in blocks), blocks)
            back.append(blocks[0]["reason"] if blocks else None)
        return back

    def test_open_work_goes_back_twice_then_the_owner_is_asked_with_its_last_words(self):
        seat = self.turn("stuck")
        self.assertEqual([reason is not None for reason in self.stops(seat, 3)],
                         [True, True, False])
        stood = time.monotonic()
        why = self.home.ak("orch", "why", "stuck")
        self.assertEqual(why.code, 0, why.err)
        self.assertEqual(why.out.splitlines()[0].split(), ["stuck", "needs", "you"], why.out)
        self.assertRegex(why.out, rf"(?m)^  reason: .*{re.escape(LAST)}$")
        # tmux keeps when someone last typed in or opened a seat, and nothing back-dates it: the
        # question sits out the owner's minute in real time, the seat's opening with it
        time.sleep(max(0.0, stood + MINUTE + 0.5 - time.monotonic()))
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.sink.pages().count("🙋 Needs you · stuck"), 1, self.sink.pages())
        page, = events(self.home, "stuck")
        self.assertEqual(page["status"], "delivered", page)
        self.assertIn(LAST, page["message"])

    def test_a_new_prompt_counts_afresh(self):
        seat = self.turn("again")
        self.assertEqual([reason is not None for reason in self.stops(seat, 2)], [True, True])
        self.hooks.prompt("Go on with the parser.", seat)
        self.assertEqual([reason is not None for reason in self.stops(seat, 3)],
                         [True, True, False])

    def test_the_stop_stands_at_once_with_no_open_line_a_question_or_a_wait(self):
        with self.subTest("no open line in the plan"):
            self.assertEqual(self.stops(self.turn("planless", planned=False), 1), [None])
        with self.subTest("a question recorded with ak notify needs"):
            seat = self.turn("asked")
            done = self.home.ak("notify", "needs", ASKED, env={"AGENTKIT_SESSION": "asked"})
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(self.stops(seat, 1, closing=ASKED), [None])
        with self.subTest("an ak wait on a run of its own still going"):
            # going: its line holds it until the lander ends it
            self.home.write(f".agentkit/runs/{RUN}/run.json",
                            {"run_id": RUN, "title": "fix-api", "state": "waiting",
                             "launched_session": "waits", "waiting_on": {"line": "acme/api"}})
            seat = self.turn("waits")
            done = self.home.ak("wait", RUN, env={"AGENTKIT_SESSION": "waits"})
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(self.stops(seat, 1, closing="Waiting on fix-api."), [None])


if __name__ == "__main__":
    unittest.main(verbosity=2)
