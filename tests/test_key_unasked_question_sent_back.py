"""A question left in prose at a turn's end goes back once to be asked.

A Claude seat's turn that may otherwise end, here one with no plan and so nothing owed, whose
last message ends in a question mark, past any closing emphasis, quote or bracket, with nothing
asked through the question card or `ak notify needs`, has its Stop sent back once with ak's
reason, as Claude's block decision on stdout; the next Stop of that turn stands.  It stands at
once where the mark is only inside the message, where `ak notify needs` recorded the question,
where an AskUserQuestion card is left unanswered, and where the seat's plan is done with nothing
from the owner since, so a question would hold only the owner.  A sub-agent's Stop decides
nothing.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
before seats of tests/fixtures/akseat.py whose hooks fire as Claude fires them
(tests/fixtures/hookdrive.py).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures import hookdrive

STOP = {"background_tasks": [], "stop_hook_active": False}
QUESTION = "Merge it?"
CLOSINGS = {"bold": f"**{QUESTION}**", "quoted": f'"{QUESTION}"', "bracketed": f"({QUESTION})"}
# Claude Code's card, still waiting on the owner: no tool_result answers it
CARD = {"type": "assistant", "message": {"role": "assistant", "content": [
    {"type": "tool_use", "id": "toolu_acme", "name": "AskUserQuestion", "input": {"questions": [
        {"question": QUESTION, "header": "Merge", "multiSelect": False,
         "options": [{"label": "Yes", "description": "merge now"},
                     {"label": "No", "description": "leave it open"}]}]}}]}}
SUB_AGENT = {"agent_id": "a1b2c3d4", "agent_type": "general-purpose"}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class UnaskedQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = hookdrive.Hooks(cls.home)

    def seat(self, name, asked=None):
        """A seat whose turn the owner began, which recorded `asked` with `ak notify needs`,
        at its prompt again."""
        seat = Seat(self.home, name, screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        if asked:
            done = self.home.ak("notify", "needs", asked, env={"AGENTKIT_SESSION": name})
            self.assertEqual(done.code, 0, done.err)
        seat.show("claude-prompt-pane.txt")
        return seat

    def sent_back(self, seat, *closing, **payload):
        """The reasons a Stop of the seat's turn, its transcript `closing`, blocked with: none
        where it stood."""
        chat = hookdrive.transcript(self.home, seat.name, *closing)
        fired = self.hooks.fire("Stop", {**STOP, "transcript_path": chat, **payload},
                                seat=seat.name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        return [out.get("reason") for out in fired.said if out.get("decision") == "block"]

    def test_a_question_left_in_prose_goes_back_once(self):
        for form, closing in CLOSINGS.items():
            with self.subTest(form):
                seat = self.seat(form)
                back = self.sent_back(seat, closing)
                self.assertEqual(len(back), 1, back)
                self.assertTrue(isinstance(back[0], str) and back[0].strip(), back)
                self.assertEqual(self.sent_back(seat, closing, stop_hook_active=True), [])

    def test_a_question_mark_only_inside_the_message_stands(self):
        seat = self.seat("inside")
        self.assertEqual(self.sent_back(seat, f"{QUESTION} Its checks passed, so I merged it."),
                         [])

    def test_a_question_recorded_with_notify_needs_stands(self):
        seat = self.seat("recorded", asked=QUESTION)
        self.assertEqual(self.sent_back(seat, CLOSINGS["bold"]), [])

    def test_an_unanswered_card_stands(self):
        seat = self.seat("card")
        self.assertEqual(self.sent_back(seat, CLOSINGS["bold"], CARD), [])

    def test_a_done_plan_with_nothing_from_the_owner_since_stands(self):
        seat = self.seat("finished")
        # every line ticked after the owner's prompt
        self.home.write(".agentkit/state/plan-finished.md", "- [x] Merge the parser\n")
        self.assertEqual(self.sent_back(seat, CLOSINGS["bold"]), [])

    def test_a_sub_agents_stop_decides_nothing(self):
        seat = self.seat("helper")
        self.assertEqual(self.sent_back(seat, CLOSINGS["bold"], **SUB_AGENT), [])
        # nor does it spend the turn's one sending back
        self.assertEqual(len(self.sent_back(seat, CLOSINGS["bold"])), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
