"""A seat moved to a model of another harness opens with its conversation so far in its rulebook,
and nothing is typed for it.

The move typed a handover -- from which model, a plan file, a transcript path -- into the new
TUI while the owner may have been typing there, and that line carried nothing of what was said.
Now the rulebook the new harness opens on ends with the conversation as the old harness reads it
back (`said`), and only a turn it was in is told to go on.  `test_seat_move_keeps_conversation`'s
stage.
"""

import time
import unittest
from unittest.mock import patch

from test_seat_move_keeps_conversation import NOW, SEAT, SeatMove
from agentkit import config, orch, watch
from agentkit.harness import Harness

ASKED = {"who": "user", "text": "Make the endpoint answer 404 for a missing id"}
ANSWERED = {"who": "model", "text": "Done: it answers 404, and its test passes."}
SAID = Harness.said     # each harness's own reader


class HandsOver(SeatMove):
    def setUp(self):
        super().setUp()
        self.said = {"claude": [ASKED, ANSWERED]}
        self.stack.enter_context(patch.object(
            Harness, "said", new=lambda plugin, *_a: self.said.get(plugin.name)))
        self.lines = []
        command = orch.command.side_effect
        orch.command.side_effect = lambda *a, line=None, **kw: (self.lines.append(line)
                                                                 or command(*a, **kw))

    def rulebook(self):
        return config.rulebook_path(SEAT).read_text()

    def test_moved_to_another_harness_it_opens_with_what_was_said_and_nothing_is_typed(self):
        self.assertEqual(self.move("astra"), "")
        rulebook = self.rulebook()
        self.assertIn("This seat ran on opus", rulebook)
        self.assertLess(rulebook.index(ASKED["text"]), rulebook.index(ANSWERED["text"]))
        self.assertIn(f"**opus:** {ANSWERED['text']}", rulebook)
        self.assertEqual({*self.lines}, {None})     # each command it was asked for
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def test_moved_mid_turn_it_opens_on_the_line_to_go_on_with_it(self):
        watch.seat_write(SEAT, state="at_prompt")
        config.record_hook_fact(SEAT, {"session": SEAT, "event": "UserPromptSubmit",
                                       "at": time.time(), "kind": "", "text": ""})
        self.move("astra")
        self.assertEqual({*self.lines}, {watch.MOVED_LINE})
        self.assertIn("handover at the end of your instructions", watch.MOVED_LINE)

    def test_moved_on_again_it_hands_on_both_conversations(self):
        self.move("astra")
        self.said["codex"] = [{"who": "user", "text": "And for a deleted one?"},
                              {"who": "model", "text": "410, as the spec says."}]
        # the thread its Codex launch hook would have reported
        with patch.object(Harness, "conversation", new=lambda *_a: "thread-of-astra"):
            self.move("fable")
        rulebook = self.rulebook()
        self.assertIn("This seat ran on astra", rulebook)
        self.assertLess(rulebook.index(ANSWERED["text"]), rulebook.index("**astra:** 410"))

    def test_the_latest_messages_are_what_fits(self):
        long = {"who": "model", "text": "Done. " * config.RULEBOOK_BYTES}
        self.said["claude"] = [ASKED, long, {"who": "user", "text": "Ship it"}]
        self.move("astra")
        rulebook = self.rulebook()
        self.assertNotIn(ASKED["text"], rulebook)
        self.assertIn("its 2 earliest messages too", rulebook)
        self.assertIn("**user:** Ship it", rulebook)

    def test_its_rulebook_with_the_handover_fits_the_one_argument_codex_takes_it_in(self):
        (config.HOME / "rules.md").write_text("Keep the endpoint compatible.\n" * 2500)
        self.said["claude"] = [{"who": "user", "text": "界" * 60000 + "Ship it"}]
        self.move("astra")
        rulebook = self.rulebook()
        self.assertIn("Keep the endpoint compatible.", rulebook)
        self.assertIn("界界Ship it", rulebook)                 # the end of what was said
        self.assertLessEqual(len(rulebook.encode()), config.RULEBOOK_BYTES)

    def test_a_seat_moved_before_its_first_word_hands_on_nothing(self):
        with patch.object(Harness, "said", new=SAID):     # Claude has written no transcript yet
            self.move("astra")
        self.assertNotIn("This seat ran on", self.rulebook())

    def test_a_harness_that_reads_nothing_back_hands_on_its_transcript(self):
        self.said.pop("claude")
        with patch.object(Harness, "transcript", return_value="/tmp/acme/transcript.jsonl"):
            self.move("astra")
        self.assertIn("raw transcript is at /tmp/acme/transcript.jsonl", self.rulebook())

    def test_each_raw_transcript_is_handed_on_in_its_place(self):
        self.said.pop("claude")
        with patch.object(Harness, "transcript", return_value="/tmp/acme/first.jsonl"):
            self.move("astra")
        self.said["codex"] = [{"who": "user", "text": "And for a deleted one?"}]
        with patch.object(Harness, "conversation", new=lambda *_a: "thread-of-astra"):
            self.move("fable")
        with patch.object(Harness, "transcript", return_value="/tmp/acme/third.jsonl"):
            self.move("astra")
        rulebook = self.rulebook()
        self.assertLess(rulebook.index("/tmp/acme/first.jsonl"),
                        rulebook.index("And for a deleted one?"))
        self.assertLess(rulebook.index("And for a deleted one?"),
                        rulebook.index("/tmp/acme/third.jsonl"))

    def test_a_move_that_fails_leaves_no_handover_behind(self):
        self.refused = "no such pane"
        self.assertTrue(self.move("astra"))
        self.assertFalse(config.seat_file("handover", SEAT).exists())
        self.assertEqual(self.record()["orchestrator"], "opus")
        self.assertEqual(NOW, orch.time.time())


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the stage's run from their own file."""
    return unittest.TestSuite(HandsOver(name) for name in loader.getTestCaseNames(HandsOver)
                              if name in vars(HandsOver))


if __name__ == "__main__":
    unittest.main()
