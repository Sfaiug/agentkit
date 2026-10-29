"""A notice is written down as its kind and its words, unless the seat's manifest says it adds
nothing to the fact standing.

A seat's row reads its word from the fact its hooks keep (`hook-<seat>.json`): the event, the
payload field that tells one kind of it from another (a notice's type, the tool a permission is
for, a compaction's trigger) and the words a person reads there, a question's own before a
notice's, whole up to 4000 characters and past them ending in `…`.  On a harness ak knows, a
notice is written only when the manifest gives it a state the fact standing does not already
mean: the permission notice Claude sends after the PermissionRequest that wrote the question
down must not replace it, and a compaction Claude starts itself must not leave a `working`
standing at a quiet prompt.  Where no record names the harness, every notice is written.
Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py); this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

QUIET = (0, "", "", [])
BASH = {"tool_name": "Bash", "tool_input": {"command": "make test"}}
NOTICE = {"notification_type": "permission_prompt", "message": "Claude needs your permission"}


class NoticeHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)
        cls.state = cls.home.path / ".agentkit" / "state"

    def setUp(self):
        for path in self.state.iterdir():
            path.unlink()

    def seat_on_claude(self):
        """The record ak's launch leaves for a seat on `opus`, a Claude model."""
        Seat(self.home, "acme", model="opus", alive=False)

    def fire(self, event, payload):
        fired = self.hooks.fire(event, payload, seat="acme")
        self.assertEqual(fired, QUIET, event)

    def fact(self):
        path = self.state / "hook-acme.json"
        return json.loads(path.read_text()) if path.exists() else None

    def said(self):
        fact = self.fact()
        return fact and (fact["event"], fact["kind"], fact["text"])

    def test_a_notice_is_written_as_its_type_and_its_message_cut_to_4000_characters(self):
        self.fire("Notification", {"notification_type": "permission_prompt", "message": "m" * 5000})
        fact = self.fact()
        self.assertEqual(fact, {"session": "acme", "event": "Notification",
                                "kind": "permission_prompt", "text": "m" * 3999 + "…",
                                "at": fact["at"]})

    def test_a_question_is_written_as_its_tool_and_its_own_words_before_the_notices(self):
        self.fire("PermissionRequest", {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which schema?"},
                                         {"question": "Which port?"}]},
            "message": "Claude needs your permission"})
        self.assertEqual(self.said(), ("PermissionRequest", "AskUserQuestion", "Which schema?"))

    def test_the_permission_notice_after_its_request_leaves_the_request_standing(self):
        self.seat_on_claude()
        self.fire("PermissionRequest", BASH)
        standing = self.fact()
        self.assertEqual(self.said(), ("PermissionRequest", "Bash", ""))
        self.fire("Notification", NOTICE)
        self.assertEqual(self.fact(), standing)

    def test_a_compaction_claude_starts_itself_is_not_written_and_one_asked_for_is(self):
        self.seat_on_claude()
        self.fire("PermissionRequest", BASH)
        standing = self.fact()
        self.fire("PreCompact", {"trigger": "auto"})
        self.assertEqual(self.fact(), standing)
        self.fire("PreCompact", {"trigger": "manual"})
        self.assertEqual(self.said(), ("PreCompact", "manual", ""))
        self.assertGreater(self.fact()["at"], standing["at"])

    def test_a_seat_no_record_names_writes_the_notice_after_its_request(self):
        self.fire("PermissionRequest", BASH)
        self.fire("Notification", NOTICE)
        self.assertEqual(self.said(), ("Notification", "permission_prompt",
                                       "Claude needs your permission"))


if __name__ == "__main__":
    unittest.main()
