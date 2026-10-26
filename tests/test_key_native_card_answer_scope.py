"""An answer on a harness's native question card answers only the questions that card asked.

A seat's questions recorded with `ak notify needs`, standing or kept back mid-turn, wait for
the owner.  Claude Code's AskUserQuestion card hands its PostToolUse hook the owner's answers
keyed by the card's own question words: a recorded question it names is answered, every other
stands, and the turn's end shows it as `needs you` again.  A card cancelled or left empty
answers nothing.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py whose hooks fire as their
harness fires them (tests/fixtures/hookdrive.py).
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures import hookdrive

STOP = {"background_tasks": [], "stop_hook_active": False}
LAYOUT = "Which layout should acme use?"
NAMING = "Which naming should acme use?"
SCOPE = "Which audit scope should acme use?"
UPDATE = "Run fix-api ended: merged."     # a run update ak types, the owner's words in none


def card(*asked, answers=None):
    """Claude Code's PostToolUse for its AskUserQuestion card, with the owner's `answers`
    keyed by the question each answers, as its native result keeps them."""
    questions = [{"question": q, "header": "Pick", "multiSelect": False,
                  "options": [{"label": "Local (Recommended)"}, {"label": "Global"}]}
                 for q in asked]
    return {"tool_name": "AskUserQuestion", "tool_use_id": "toolu_acme",
            "tool_input": {"questions": questions},
            "tool_response": {"questions": questions, "answers": answers or {}}}


def why(home, seat):
    """The seat's first line and its reason, as `ak orch why` gives them."""
    done = home.ak("orch", "why", seat)
    assert done.code == 0, done.err
    lines = done.out.splitlines()
    return lines[0], next(line.split(":", 1)[1].strip() for line in lines
                          if line.strip().startswith("reason:"))


def settled(home, seat, word, bound=10):
    """`why` once the seat reads that word: a hook's look at the seat runs a moment after it."""
    deadline = time.monotonic() + bound
    while (got := why(home, seat))[0] != f"{seat}  {word}" and time.monotonic() < deadline:
        time.sleep(0.1)
    return got


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NativeCardAnswerScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = hookdrive.Hooks(cls.home)

    def ask(self, seat, *questions):
        for question in questions:
            done = self.home.ak("notify", "needs", question, env={"AGENTKIT_SESSION": seat.name})
            self.assertEqual(done.code, 0, done.err)

    def answer(self, seat, payload):
        fired = self.hooks.fire("PostToolUse", payload, seat=seat.name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)

    def stop(self, seat, *said):
        """The turn ends, its closing chat saying `said`."""
        seat.show("claude-prompt-pane.txt")
        chat = hookdrive.transcript(self.home, seat.name, *said) if said else None
        self.hooks.fire("Stop", {**STOP, **({"transcript_path": chat} if chat else {})},
                        seat=seat.name, pane=seat)

    def standing(self, seat, *questions):
        """Questions recorded and shown at a turn's end, then a run update starts a new turn."""
        self.hooks.prompt("go", seat)
        seat.show("claude-working-pane.txt")
        self.ask(seat, *questions)
        self.stop(seat, " ".join(questions))
        self.assertEqual(settled(self.home, seat.name, "needs you")[0], f"{seat.name}  needs you")
        self.hooks.fire("UserPromptSubmit", {"prompt": UPDATE}, seat=seat.name, pane=seat)
        seat.show("claude-working-pane.txt")

    def test_a_card_answers_only_the_standing_question_it_asked(self):
        seat = Seat(self.home, "acme")
        self.standing(seat, LAYOUT, NAMING)
        self.answer(seat, card(NAMING, SCOPE, answers={NAMING: "Local (Recommended)",
                                                       SCOPE: "Local (Recommended)"}))
        self.assertEqual(settled(self.home, "acme", "working"), ("acme  working", "-"))
        self.stop(seat, LAYOUT)
        self.assertEqual(settled(self.home, "acme", "needs you"), ("acme  needs you", LAYOUT))

    def test_a_card_answers_its_kept_question_and_leaves_the_other_kept(self):
        seat = Seat(self.home, "beta", screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        self.ask(seat, LAYOUT, NAMING)
        self.assertEqual(why(self.home, "beta"), ("beta  working", "-"))
        self.answer(seat, card(LAYOUT, answers={LAYOUT: "Global"}))
        self.stop(seat, NAMING)
        self.assertEqual(settled(self.home, "beta", "needs you"), ("beta  needs you", NAMING))
        # the owner's chat answers what still stands, as it always has
        self.hooks.prompt("snake_case", seat)
        seat.show("claude-working-pane.txt")
        self.assertEqual(settled(self.home, "beta", "working"), ("beta  working", "-"))
        self.stop(seat)
        self.assertEqual(settled(self.home, "beta", "idle"), ("beta  idle", "-"))

    def test_a_cancelled_or_empty_card_answers_nothing(self):
        for name, payload in (("gamma", card(LAYOUT)),
                              ("delta", card(LAYOUT, answers={LAYOUT: " "}))):
            with self.subTest(name):
                seat = Seat(self.home, name)
                self.standing(seat, LAYOUT)
                self.answer(seat, payload)
                self.stop(seat, LAYOUT)
                self.assertEqual(settled(self.home, name, "needs you"),
                                 (f"{name}  needs you", LAYOUT))


if __name__ == "__main__":
    unittest.main(verbosity=2)
