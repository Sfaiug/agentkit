"""A recorded question reaches the chat inline or with its choices as Markdown bullets.

A seat's question, recorded with `ak notify needs` mid-turn, lets its turn end once the closing
assistant message shows the title, the recommendation and every choice: as recorded, or as a
Markdown list, read as the recorded `a, b.`  A choice left out, its label changed (`snake case`
for `snake_case`) or a comma dropped is not the question, and the Stop goes back with it.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before
seats of tests/fixtures/akseat.py whose hooks fire as their harness fires them
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
# as Claude Code 2.1.305 recorded it, and the closing messages it might show it in
ASKED = "Which naming should acme use? Options: snake_case (Recommended), camelCase."
BULLETS = "Which naming should acme use?\n\n- snake_case (Recommended)\n- camelCase"
SHOWN = {"inline": ASKED, "bullets": BULLETS}
UNSHOWN = {"a choice left out": "Which naming should acme use?\n\n- snake_case (Recommended)",
           "a label changed": BULLETS.replace("snake_case", "snake case"),
           # inline, a comma can as well be a label's own as the list's
           "a comma dropped": ASKED.replace(",", "")}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class QuestionChatFormat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = hookdrive.Hooks(cls.home)

    def sent_back(self, name, closing):
        """What the Stop of a turn that recorded the question and closed on `closing` sent
        back: the reasons it blocked with, none where it stood."""
        seat = Seat(self.home, name, screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        done = self.home.ak("notify", "needs", ASKED, env={"AGENTKIT_SESSION": name})
        self.assertEqual(done.code, 0, done.err)
        seat.show("claude-prompt-pane.txt")
        chat = hookdrive.transcript(self.home, name, closing)
        fired = self.hooks.fire("Stop", {**STOP, "transcript_path": chat}, seat=name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        return [out["reason"] for out in fired.said if out.get("decision") == "block"]

    def test_the_question_shown_inline_or_as_bullets_ends_the_turn(self):
        for form, closing in SHOWN.items():
            with self.subTest(form):
                self.assertEqual(self.sent_back(form.replace(" ", "-"), closing), [])

    def test_a_choice_left_out_or_changed_sends_the_question_back(self):
        for form, closing in UNSHOWN.items():
            with self.subTest(form):
                back = self.sent_back(form.replace(" ", "-"), closing)
                self.assertEqual(len(back), 1, back)
                self.assertIn(ASKED, back[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
