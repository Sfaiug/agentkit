"""A seat's own question reads `needs you` until the owner answers; a Muse one only by its hook.

A seat's word tells the owner when only they can unblock it.  A question the seat asks with
`ak notify needs` is that: the seat's word is `needs you`, the question its reason, until the
owner's next prompt answers it.  One asked mid-turn waits for the turn's end, since until then
the seat works on.  Muse asks with a question tool of its own, whose dialog only its
`question_prompt` notification says is open.  Output can quote that dialog, so the screen alone
never asks, and an answered question gives way to the turn.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, before seats of
tests/fixtures/akseat.py whose hooks fire as their harness fires them (tests/fixtures/hookdrive.py).
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import FIXTURES, Seat
from fixtures import hookdrive

STOP = {"background_tasks": [], "stop_hook_active": False}
# What Muse 1.4.7 handed its hook as its question dialog opened, as captured.
ASKED = json.loads((FIXTURES / "muse-hook-payloads.jsonl").read_text().splitlines()[0])
BANNER = "Which colour should the acme banner use?"    # the question on muse-question-pane.txt


def why(home, seat):
    """The seat's first line and its reason, as `ak orch why` gives them."""
    done = home.ak("orch", "why", seat)
    assert done.code == 0, done.err
    lines = done.out.splitlines()
    reason = next(line.split(":", 1)[1].strip() for line in lines
                  if line.strip().startswith("reason:"))
    return lines[0], reason


def row(home, seat):
    """The seat's row in `ak orch list`."""
    done = home.ak("orch", "list")
    assert done.code == 0, done.err
    return next(line for line in done.out.splitlines() if line.startswith(f"{seat} "))


def settled(home, seat, word, bound=10):
    """`why` once the seat reads that word: a hook's look at the seat runs a moment after it."""
    deadline = time.monotonic() + bound
    while (got := why(home, seat))[0] != f"{seat}  {word}" and time.monotonic() < deadline:
        time.sleep(0.1)
    return got


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ItsOwnQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = hookdrive.Hooks(cls.home)

    def test_a_question_kept_for_the_seat_reads_needs_you_with_it_as_the_reason(self):
        Seat(self.home, "acme")
        # as an earlier ak left the seat's question, for the build reading it now
        self.home.write(".agentkit/state/notify-acme.json",
                        {"session": "acme", "kind": "needs", "text": "Which colour do you want?",
                         "time": time.time()})
        self.assertEqual(why(self.home, "acme"), ("acme  needs you", "Which colour do you want?"))
        self.assertIn("! needs you", row(self.home, "acme"))

    def test_one_asked_at_the_prompt_reads_needs_you_at_once(self):
        seat = Seat(self.home, "beta")
        self.hooks.fire("Stop", STOP, seat="beta", pane=seat)
        done = self.home.ak("notify", "needs", "Which schema?", env={"AGENTKIT_SESSION": "beta"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(settled(self.home, "beta", "needs you"),
                         ("beta  needs you", "Which schema?"))
        self.assertIn("! needs you", row(self.home, "beta"))

    def test_one_asked_mid_turn_reads_needs_you_from_its_end_until_the_owner_answers(self):
        seat = Seat(self.home, "fix-api", screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        done = self.home.ak("notify", "needs", "Which port?", env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(why(self.home, "fix-api"), ("fix-api  working", "-"))
        seat.show("claude-prompt-pane.txt")
        self.hooks.fire("Stop", STOP, seat="fix-api", pane=seat)
        self.assertEqual(settled(self.home, "fix-api", "needs you"),
                         ("fix-api  needs you", "Which port?"))
        # the owner's prompt answers it, and the turn it starts ends with nothing asked
        self.hooks.prompt("8080", seat)
        seat.show("claude-working-pane.txt")
        self.assertEqual(settled(self.home, "fix-api", "working"), ("fix-api  working", "-"))
        seat.show("claude-prompt-pane.txt")
        self.hooks.fire("Stop", STOP, seat="fix-api", pane=seat)
        self.assertEqual(settled(self.home, "fix-api", "idle"), ("fix-api  idle", "-"))
        self.assertIn("○ idle", row(self.home, "fix-api"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # A seat's harness runs inside its tmux server, $TMUX naming it, and Muse's hook reads
        # the question from the seat's pane there; the Home's tmux takes no caller's server.
        cls.seat_bin = cls.home.root / "seat-bin"
        cls.seat_bin.mkdir()
        (cls.seat_bin / "tmux").symlink_to(REAL_TMUX)

    def muse_seat(self, name, screen="muse-question-pane.txt"):
        return Seat(self.home, name, model="spark", screen=screen)

    def ask(self, seat):
        """Muse opening its question dialog, its hook run in the seat as its launch set it."""
        fired = hookdrive.adapter(self.home, "muse", "hook", payload=ASKED, seat=seat.name,
                                  pane=seat,
                                  env={"PATH": f"{self.seat_bin}:{self.home.env['PATH']}"})
        self.assertEqual(fired.code, 0, fired.err)

    def test_its_question_hook_over_the_dialog_reads_needs_you_with_the_question(self):
        self.ask(self.muse_seat("acme"))
        self.assertEqual(settled(self.home, "acme", "needs you"), ("acme  needs you", BANNER))
        self.assertIn("! needs you", row(self.home, "acme"))

    def test_a_question_on_screen_with_no_hook_never_reads_needs_you(self):
        seat = self.muse_seat("beta")
        for screen in ("muse-question-pane.txt", "muse-question-asked-pane.txt",
                       "muse-question-review-pane.txt"):
            with self.subTest(screen=screen):
                seat.show(screen)
                self.assertNotEqual(why(self.home, "beta")[0], "beta  needs you")
                self.assertNotIn("needs you", row(self.home, "beta"))

    def test_an_answered_question_gives_way_to_the_turn_and_then_the_prompt(self):
        seat = self.muse_seat("fix-api")
        self.ask(seat)
        self.assertEqual(settled(self.home, "fix-api", "needs you")[0], "fix-api  needs you")
        seat.show("muse-question-answered-pane.txt")
        self.assertEqual(settled(self.home, "fix-api", "working"), ("fix-api  working", "-"))
        self.assertIn("● working", row(self.home, "fix-api"))
        seat.show("muse-prompt-pane.txt")
        self.assertEqual(settled(self.home, "fix-api", "idle"), ("fix-api  idle", "-"))


if __name__ == "__main__":
    unittest.main()
