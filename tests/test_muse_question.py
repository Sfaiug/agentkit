"""A question Muse asks with its own tool reads as asking, and its seat needs the owner.

Muse 1.4.7's `Request user input` draws its options and key hint over a composer it keeps open,
and its hint ends `Esc to interrupt`: the working rule read it, so the seat said `working`, no
card went out, and the turn waited on an answer nobody was told about.
"""
import unittest

from fixtures.sandbox import REPO
from agentkit import watch

QUESTION = (REPO / "tests/fixtures/muse-question-pane.txt").read_text(encoding="utf-8")
HINT = ("Enter to select · ↑/↓ to move · ←/→ to switch question · "
        "Tab for an optional note · Esc to interrupt")


def pane(name):
    return (REPO / f"tests/fixtures/muse-{name}-pane.txt").read_text(encoding="utf-8")


class MuseQuestion(unittest.TestCase):

    def test_its_own_question_tool_reads_as_asking_under_a_draft_too(self):
        draft = next(row for row in pane("draft").splitlines()
                     if watch.strip_sgr(row).startswith("❯ "))
        for name, text in (("empty", QUESTION), ("draft", QUESTION.replace("❯ ", draft))):
            state, rule, evidence = watch.screen_state("muse", watch.pane_tail(text))
            self.assertEqual((state, rule, evidence), ("asking", "asking.question", HINT), name)

    def test_its_prompt_and_its_turn_still_read_as_before(self):
        for name, state in (("prompt", "at_prompt"), ("working", "working")):
            self.assertEqual(watch.screen_state("muse", watch.pane_tail(pane(name)))[0],
                             state, name)

    def test_a_turn_quoting_its_key_hint_is_still_a_turn(self):
        working, thinking = pane("working"), "◇ Thinking (0s · esc to interrupt)"
        for name, text in (
                ("echoed prompt", working.replace("Say OK", "Explain this key hint: " + HINT)),
                ("draft", working.replace("❯\n", "❯ Explain this hint:\n  " + HINT + "\n")),
                ("output", working.replace(thinking, thinking + "\n" + HINT))):
            self.assertEqual(watch.screen_state("muse", watch.pane_tail(text))[:2],
                             ("working", "working.interrupt"), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
