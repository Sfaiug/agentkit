"""A seat takes back a question it no longer needs the owner for: `ak notify settled`.

A question a seat asks reads `needs you`, pages the owner and must be written again at every
turn's end until the owner answers.  One that is over without them -- another seat did what it
asked about -- is the seat's to take back, with a command as it asked with one: every question
it asks, standing or kept back for its turn's end, ends as the owner's stop ends it.  Its word
changes at once, a page still waiting is never sent, and a question taken back ends no turn,
not even the one it was asked in.  The block that sends a turn back to write its questions
again names the command.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py whose hooks fire as Claude
fires them (tests/fixtures/hookdrive.py), paging tests/fixtures/sink.py, which answers every
page 503; each tick runs in `home.tick()`'s box.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, boxable, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks
from fixtures.sink import Sink
from fixtures import akconfig, hookdrive

QUESTION = "Should I restart the acme build machine?"
SAID = "The parser still needs work."
STOP = {"background_tasks": [], "stop_hook_active": False}
OVER = ("disabled", "the question it asked is over")


def settled(home, seat):
    """`ak notify settled`, run in that seat."""
    return home.ak("notify", "settled", env={"AGENTKIT_SESSION": seat})


def took_back(test, home, seat):
    done = settled(home, seat)
    test.assertEqual(done.code, 0, done.err)
    test.assertEqual(done.out, f"{seat}: took back {QUESTION}\n")


def why(home, seat):
    """The seat's first line and its reason, as `ak orch why` gives them."""
    done = home.ak("orch", "why", seat)
    assert done.code == 0, done.err
    lines = done.out.splitlines()
    return lines[0], next(line.split(":", 1)[1].strip() for line in lines
                          if line.strip().startswith("reason:"))


def reads(home, seat, word, bound=10):
    """`why` once the seat reads that word: a hook's look at the seat runs a moment after it."""
    deadline = time.monotonic() + bound
    while (got := why(home, seat))[0] != f"{seat}  {word}" and time.monotonic() < deadline:
        time.sleep(0.1)
    return got


def standing(home, seat):
    """The seat's notice where one stands, else None: one taken back stands no more."""
    path = home.path / f".agentkit/state/notify-{seat}.json"
    notice = json.loads(path.read_text()) if path.exists() else {}
    return notice if notice and not notice.get("seen") else None


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ItsWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def test_a_question_taken_back_reads_needs_you_no_more(self):
        seat = Seat(self.home, "acme")
        self.hooks.fire("Stop", STOP, seat="acme", pane=seat)
        done = self.home.ak("notify", "needs", QUESTION, env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(reads(self.home, "acme", "needs you"), ("acme  needs you", QUESTION))
        took_back(self, self.home, "acme")
        self.assertEqual(reads(self.home, "acme", "idle"), ("acme  idle", "-"))
        self.assertIsNone(standing(self.home, "acme"))

    def test_one_asked_mid_turn_and_taken_back_in_it_is_never_asked(self):
        seat = Seat(self.home, "fix-api", screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        done = self.home.ak("notify", "needs", QUESTION, env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(done.code, 0, done.err)
        took_back(self, self.home, "fix-api")
        seat.show("claude-prompt-pane.txt")
        said = hookdrive.transcript(self.home, "fix-api", SAID)
        fired = self.hooks.fire("Stop", {**STOP, "transcript_path": said}, seat="fix-api",
                                pane=seat)
        self.assertEqual((fired.code, fired.said), (0, []))
        self.assertEqual(reads(self.home, "fix-api", "idle"), ("fix-api  idle", "-"))
        self.assertIsNone(standing(self.home, "fix-api"))


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ItsPage(unittest.TestCase):
    def test_a_page_waiting_for_its_retry_is_never_sent(self):
        with Home() as home:
            akconfig.write(home, ["opus"])    # with no audit seat for a tick to open
            sink = Sink(home)
            self.addCleanup(sink.close)
            sink.script(*[503] * 100)
            Seat(home, "fix-api")

            def page():
                found = [json.loads(path.read_text()) for path in
                         (home.path / ".agentkit/state/notification-outbox").glob("*.json")]
                event, = [event for event in found if event.get("session") == "fix-api"]
                return event["status"], event.get("error")

            done = home.ak("notify", "needs", QUESTION, "--session", "fix-api")
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(page(), ("pending", "HTTP 503"))
            took_back(self, home, "fix-api")
            self.assertEqual(page(), OVER)
            ticked = home.tick()
            self.assertEqual(ticked.code, 0, ticked.err)
            self.assertEqual(page(), OVER)
            self.assertEqual([p for p in sink.pages() if p == "🙋 Needs you · fix-api"],
                             ["🙋 Needs you · fix-api"])


class ItsTurn(unittest.TestCase):
    def test_a_question_taken_back_ends_no_turn_even_the_one_it_was_asked_in(self):
        for ending in ("wait", "plan"):
            for reminded in (True, False):
                with self.subTest(ending=ending, reminded=reminded), Home() as home:
                    hooks = Hooks(home)

                    def fire(seat, event, **payload):
                        result = hooks.fire(event, payload, seat=seat, finished=True)
                        self.assertEqual(result.code, 0, result.err)
                        return result.said

                    # beta works as acme does and asks nothing: its stop is any stop
                    for seat in ("acme", "beta"):
                        home.write(f".agentkit/state/plan-{seat}.md", "- [ ] fix the parser\n")
                        fire(seat, "UserPromptSubmit", prompt="go")
                    done = home.ak("notify", "needs", QUESTION, "--session", "acme")
                    self.assertEqual(done.code, 0, done.err)
                    if reminded:
                        said = fire("acme", "Stop", last_assistant_message=SAID)
                        self.assertEqual([out["decision"] for out in said], ["block"])
                        self.assertIn(QUESTION, said[0]["reason"])
                        self.assertIn("ak notify settled", said[0]["reason"])
                    took_back(self, home, "acme")
                    if ending == "wait":
                        home.write(".agentkit/runs/acme-parser/run.json", {
                            "run_id": "acme-parser", "launched_session": "acme",
                            "state": "running"})
                        done = home.ak("wait", "acme-parser", env={"AGENTKIT_SESSION": "acme"})
                        self.assertEqual(done.code, 0, done.err)
                        self.assertEqual(fire("acme", "Stop", last_assistant_message=SAID), [])
                    else:
                        said = fire("acme", "Stop", last_assistant_message=SAID)
                        anyone = fire("beta", "Stop", last_assistant_message=SAID)
                        self.assertEqual([out["decision"] for out in anyone], ["block"])
                        self.assertEqual(said, anyone)


class NothingToTakeBack(unittest.TestCase):
    def test_a_seat_asking_nothing_says_so_and_outside_a_seat_it_is_refused(self):
        with Home() as home:
            done = settled(home, "acme")
            self.assertEqual((done.code, done.out), (0, "acme: asks no question\n"), done.err)
            for env in ({}, {"AGENTKIT_SESSION": ""}):
                with self.subTest(env=env):
                    done = home.ak("notify", "settled", env=env)
                    self.assertEqual(done.code, 2, done.out)
                    self.assertTrue(done.err.strip())


if __name__ == "__main__":
    unittest.main()
