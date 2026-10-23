"""A seat moved to a model of another harness reads its conversation so far from a file its
rulebook names, and nothing is typed for it.

The move typed a handover -- from which model, a plan file, a transcript path -- into the new
TUI while the owner may have been typing there, and that line carried nothing of what was said.
Putting the conversation into the rulebook itself killed a Codex seat with E2BIG: Codex takes its
rulebook as one argument, which Linux caps at 128 KiB.  Now each move appends the conversation as
the old harness reads it back (`said`) to the seat's handover file, the rulebook's last section
names that file, and only a turn it was in is told to go on.  `test_seat_move_keeps_conversation`'s
stage.
"""

import time
import unittest
from unittest.mock import patch

from test_seat_move_keeps_conversation import SEAT, SeatMove
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
        self.handed = config.seat_file("handover", SEAT)

    def rulebook(self):
        return config.rulebook_path(SEAT).read_text()

    def handover(self):
        return self.handed.read_text()

    def move_on(self, model):
        """A move off the Codex seat, on the thread its launch hook would have reported."""
        with patch.object(Harness, "conversation", new=lambda *_a: "thread-of-astra"):
            return self.move(model)

    def test_moved_to_another_harness_it_reads_what_was_said_and_nothing_is_typed(self):
        self.assertEqual(self.move("astra"), "")
        self.assertIn(str(self.handed), self.rulebook().rpartition("\n# ")[2])   # its last section
        handover = self.handover()
        self.assertIn("## Its conversation on opus", handover)
        self.assertLess(handover.index(f"**user:** {ASKED['text']}"),
                        handover.index(f"**opus:** {ANSWERED['text']}"))
        self.assertEqual({*self.lines}, {None})     # each command it was asked for
        self.assertIsNone(watch.seat_read(SEAT).get("midturn"))

    def test_moved_mid_turn_it_opens_on_the_line_to_go_on_with_it(self):
        watch.seat_write(SEAT, state="at_prompt")
        config.record_hook_fact(SEAT, {"session": SEAT, "event": "UserPromptSubmit",
                                       "at": time.time(), "kind": "", "text": ""})
        self.move("astra")
        self.assertEqual({*self.lines}, {watch.MOVED_LINE})

    def test_moved_on_again_it_keeps_the_first_conversation_ahead_of_the_second(self):
        self.move("astra")
        self.said["codex"] = [{"who": "user", "text": "And for a deleted one?"},
                              {"who": "model", "text": "410, as the spec says."}]
        self.move_on("fable")
        handover = self.handover()
        self.assertLess(handover.index(f"**opus:** {ANSWERED['text']}"),
                        handover.index("## Its conversation on astra"))
        self.assertLess(handover.index("## Its conversation on astra"),
                        handover.index("**astra:** 410"))
        self.assertIn(str(self.handed), self.rulebook())

    def test_its_rulebook_grows_by_the_same_paragraph_whatever_was_said(self):
        (config.HOME / "rules.md").write_text("Keep the endpoint compatible.\n" * 2500)
        before = config.seat_rulebook(SEAT)
        self.said["claude"] = [{"who": "user", "text": "界" * 60000 + "Ship it"}]
        self.move("astra")
        rulebook = self.rulebook()
        self.assertTrue(rulebook.startswith(before.rstrip()))
        self.assertLess(len(rulebook.encode()) - len(before.encode()), 600)
        self.assertIn("界界Ship it", self.handover())       # the end of what was said

    def test_a_seat_moved_before_its_first_word_hands_on_nothing(self):
        with patch.object(Harness, "said", new=SAID):     # Claude has written no transcript yet
            self.move("astra")
        self.assertFalse(self.handed.exists())
        self.assertNotIn(str(self.handed), self.rulebook())

    def test_a_seat_that_said_nothing_since_it_last_moved_adds_nothing(self):
        self.move("astra")
        handover = self.handover()
        self.said["codex"] = []
        self.move_on("fable")
        self.assertEqual(self.handover(), handover)

    def test_renamed_it_keeps_the_file_its_running_rulebook_names(self):
        self.move("astra")
        handover = self.handover()
        config.rename_session(SEAT, "acme-api")
        self.assertEqual(self.handover(), handover)        # under the name it was launched with
        self.said["codex"] = [{"who": "user", "text": "And for a deleted one?"}]
        with patch.object(Harness, "conversation", new=lambda *_a: "thread-of-astra"):
            orch.switch_orchestrator(self.cfg, "acme-api", "fable", providers={})
        moved = config.seat_file("handover", "acme-api")
        self.assertIn(str(moved), config.rulebook_path("acme-api").read_text())
        self.assertLess(moved.read_text().index(ANSWERED["text"]),
                        moved.read_text().index("And for a deleted one?"))

    def test_a_harness_that_reads_nothing_back_hands_on_its_transcript(self):
        self.said.pop("claude")
        with patch.object(Harness, "transcript", return_value="/tmp/acme/transcript.jsonl"):
            self.move("astra")
        self.assertIn("raw transcript is at /tmp/acme/transcript.jsonl", self.handover())

    def test_a_conversation_nothing_can_read_is_noted_as_such(self):
        self.said.pop("claude")
        self.move("astra")
        self.assertIn("## Its conversation on opus\n\nIt cannot be read here.", self.handover())

    def test_each_raw_transcript_is_handed_on_in_its_place(self):
        self.said.pop("claude")
        with patch.object(Harness, "transcript", return_value="/tmp/acme/first.jsonl"):
            self.move("astra")
        self.said["codex"] = [{"who": "user", "text": "And for a deleted one?"}]
        self.move_on("fable")
        with patch.object(Harness, "transcript", return_value="/tmp/acme/third.jsonl"):
            self.move("astra")
        handover = self.handover()
        self.assertLess(handover.index("/tmp/acme/first.jsonl"),
                        handover.index("And for a deleted one?"))
        self.assertLess(handover.index("And for a deleted one?"),
                        handover.index("/tmp/acme/third.jsonl"))

    def test_a_move_that_fails_leaves_the_file_as_it_was(self):
        self.refused = "no such pane"
        self.assertTrue(self.move("astra"))
        self.assertFalse(self.handed.exists())
        self.assertEqual(self.record()["orchestrator"], "opus")
        self.refused = None
        self.move("astra")
        handover = self.handover()
        self.said["codex"] = [{"who": "user", "text": "And for a deleted one?"}]
        self.refused = "no such pane"
        self.assertTrue(self.move_on("fable"))
        self.assertEqual(self.handover(), handover)
        self.assertEqual(self.record()["orchestrator"], "astra")


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the stage's run from their own file."""
    return unittest.TestSuite(HandsOver(name) for name in loader.getTestCaseNames(HandsOver)
                              if name in vars(HandsOver))


if __name__ == "__main__":
    unittest.main()
