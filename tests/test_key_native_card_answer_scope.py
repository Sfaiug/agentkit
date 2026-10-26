"""An answer on a harness's native question card answers only the questions that card asked.

A seat's questions recorded with `ak notify needs`, standing or kept back mid-turn, wait for
the owner.  Claude Code's AskUserQuestion card hands its PostToolUse hook the owner's answers
keyed by the card's own question words, the choices it showed beside them: a recorded question
it names is answered, whether recorded with those choices or without, every other stands, and
the turn's end shows it as `needs you` again until the owner answers it.  A card cancelled or
left empty, or showing other choices, answers nothing.  Black-box: the program `AK_BIN` names runs from outside through
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
CHOICES = {LAYOUT: ["Compact (Recommended)", "Wide"], NAMING: ["snake_case (Recommended)", "camelCase"],
           SCOPE: ["Local (Recommended)", "Global"]}
# each as the seat records it, its choices in its words, as Claude Code 2.1.305 seats did
ASKED = {q: f"{q} Options: {', '.join(shown)}." for q, shown in CHOICES.items()}
UPDATE = "Run fix-api ended: merged."     # a run update ak types, the owner's words in none


def card(*asked, answers=None, shown=None):
    """Claude Code 2.1.305's PostToolUse for its AskUserQuestion card, each question showing
    its choices (or `shown`), with the owner's `answers` keyed by the question alone."""
    questions = [{"question": q, "header": "Pick", "multiSelect": False,
                  "options": [{"label": label, "description": f"{label} for acme."}
                              for label in shown or CHOICES[q]]}
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


def settled(home, seat, word, reason=None, bound=10):
    """`why` once the seat reads that word, and that reason where one is given: a hook's look at
    the seat, an answer's too, runs a moment after it."""
    deadline = time.monotonic() + bound
    while ((got := why(home, seat))[0] != f"{seat}  {word}" or reason not in (None, got[1])) \
            and time.monotonic() < deadline:
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
        """The owner answers the card; its model then goes on, while the hook's work ends."""
        fired = self.hooks.fire("PostToolUse", payload, seat=seat.name, pane=seat, finished=True)
        self.assertEqual(fired.code, 0, fired.err)

    def stop(self, seat, said=""):
        """The turn ends, its closing chat saying `said`; a Stop sent back goes on as Claude
        Code's turn does, its model closing again with what the hook asked, until one stands."""
        for again in range(4):
            seat.show("claude-prompt-pane.txt")
            chat = hookdrive.transcript(self.home, seat.name, said) if said else None
            fired = self.hooks.fire("Stop", {**STOP, "stop_hook_active": again > 0,
                                             **({"transcript_path": chat} if chat else {})},
                                    seat=seat.name, pane=seat)
            back = [out["reason"] for out in fired.said if out.get("decision") == "block"]
            if not back:
                return
            seat.show("claude-working-pane.txt")
            said = " ".join((said, *back))
        self.fail(f"every Stop was sent back: {back}")

    def standing(self, seat, *questions):
        """Questions recorded and shown at a turn's end, then a run update starts a new turn."""
        self.hooks.prompt("go", seat)
        seat.show("claude-working-pane.txt")
        self.ask(seat, *questions)
        self.stop(seat, " ".join(questions))
        self.assertEqual(settled(self.home, seat.name, "needs you")[0], f"{seat.name}  needs you")
        self.hooks.fire("UserPromptSubmit", {"prompt": UPDATE}, seat=seat.name, pane=seat)
        seat.show("claude-working-pane.txt")

    def naming_remains(self, seat):
        """The turn ends on naming alone, `needs you`; the owner's chat answers it, as it always
        has, and the seat is left idle."""
        self.stop(seat, ASKED[NAMING])
        self.assertEqual(settled(self.home, seat.name, "needs you", ASKED[NAMING]),
                         (f"{seat.name}  needs you", ASKED[NAMING]))
        self.hooks.prompt("snake_case", seat)
        seat.show("claude-working-pane.txt")
        self.assertEqual(settled(self.home, seat.name, "working", "-"), (f"{seat.name}  working", "-"))
        self.stop(seat)
        self.assertEqual(settled(self.home, seat.name, "idle", "-"), (f"{seat.name}  idle", "-"))

    def test_a_card_answers_only_the_standing_question_it_asked(self):
        seat = Seat(self.home, "acme")
        self.standing(seat, ASKED[LAYOUT], ASKED[NAMING])
        self.answer(seat, card(LAYOUT, SCOPE, answers={LAYOUT: "Compact (Recommended)",
                                                       SCOPE: "Local (Recommended)"}))
        self.assertEqual(settled(self.home, "acme", "working"), ("acme  working", "-"))
        self.naming_remains(seat)

    def test_a_card_answers_its_kept_question_and_leaves_the_other_kept(self):
        seat = Seat(self.home, "beta", screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        self.ask(seat, ASKED[LAYOUT], ASKED[NAMING])
        self.assertEqual(why(self.home, "beta"), ("beta  working", "-"))
        self.answer(seat, card(LAYOUT, answers={LAYOUT: "Compact (Recommended)"}))
        self.naming_remains(seat)

    def test_a_cancelled_empty_or_other_card_answers_nothing(self):
        for name, payload in (("gamma", card(LAYOUT)),
                              ("delta", card(LAYOUT, answers={LAYOUT: " "})),
                              ("epsilon", card(LAYOUT, answers={LAYOUT: "Wide"}, shown=["Wide"]))):
            with self.subTest(name):
                seat = Seat(self.home, name)
                self.standing(seat, ASKED[LAYOUT])
                self.answer(seat, payload)
                self.stop(seat, ASKED[LAYOUT])
                self.assertEqual(settled(self.home, name, "needs you", ASKED[LAYOUT]),
                                 (f"{name}  needs you", ASKED[LAYOUT]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
