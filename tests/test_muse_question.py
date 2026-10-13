"""A question Muse asks with its own tool reads as asking, and its seat needs the owner.

Muse 1.4.7's `Request user input` draws its options and key hint over a composer it keeps open,
and its hint ends `Esc to interrupt`: the working rule read it, so the seat said `working`, no
card went out, and the turn waited on an answer nobody was told about.
"""
import unittest

from fixtures.sandbox import REPO
from agentkit import watch

QUESTION = (REPO / "tests/fixtures/muse-question-pane.txt").read_text(encoding="utf-8")


class MuseQuestion(unittest.TestCase):

    def test_its_own_question_tool_reads_as_asking(self):
        state, rule, evidence = watch.screen_state("muse", watch.pane_tail(QUESTION))
        self.assertEqual((state, rule), ("asking", "asking.question"))
        self.assertIn("Enter to select", evidence)

    def test_its_prompt_and_its_turn_still_read_as_before(self):
        for name, state in (("prompt", "at_prompt"), ("working", "working")):
            pane = (REPO / f"tests/fixtures/muse-{name}-pane.txt").read_text(encoding="utf-8")
            self.assertEqual(watch.screen_state("muse", watch.pane_tail(pane))[0], state, name)

    def test_a_prompt_quoting_its_key_hint_is_still_a_turn(self):
        pane = (REPO / "tests/fixtures/muse-working-pane.txt").read_text(encoding="utf-8")
        hint = ("Enter to select · ↑/↓ to move · ←/→ to switch question · "
                "Tab for an optional note · Esc to interrupt")
        pane = pane.replace("Say OK", "Explain this key hint: " + hint)
        self.assertEqual(watch.screen_state("muse", watch.pane_tail(pane))[:2],
                         ("working", "working.interrupt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
