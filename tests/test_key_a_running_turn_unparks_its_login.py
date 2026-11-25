"""A running turn unparks the login it ran on: a Stop judges the turn it ends by the later of its
start and the last tool's result on its record, after which Claude Code sent the request the
model last answered, that answer's entry written yet or not.  A refusal made after the seat's
prompt was heard and before that result goes; one made after it stays, and so does every one
where no result outside a sidechain stands after the owner's last words.

The Home, its seat and its refusals are tests/fixtures/unparking.py's.  Each refusal and each
entry written here is dated whole seconds past a moment read once the prompt hook has returned,
later than the turn's.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.unparking import LOGINS, Unparking

BEFORE, MARKED, AFTER, SAID, ANSWERED = 1, 2, 3, 4, 5     # seconds past the prompt hook
WORDS = "The api is fixed and its tests pass."


def stamp(at):
    """A moment as Claude Code's transcripts write it."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def result(at):
    return {"type": "user", "timestamp": stamp(at), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_acme", "content": "tests pass"}]}}


def sidechains(at):
    """A tool's result in a subagent's sidechain."""
    return {**result(at), "isSidechain": True}


def said(at):
    """The owner's words, typed while the turn ran."""
    return {"type": "user", "timestamp": stamp(at), "message": {
        "role": "user", "content": "and the docs"}}


def answer(at):
    return {"type": "assistant", "timestamp": stamp(at), "message": {
        "id": "msg_answer", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": WORDS}]}}


class ARunningTurnUnparksItsLogin(Unparking):
    def ran(self, *record):
        """Both logins refused MARKED past the prompt of a turn on the second; its record then
        holds `record`, (an entry of a moment, seconds past that prompt) each -- a tool's result
        after the refusals and the model's answer where none is given -- and its Stop hands over
        the model's last words, as Claude Code's does."""
        seat = self.seat("acme")
        self.prompt(seat)
        heard = time.time()     # the prompt hook dated the turn before this
        for login in LOGINS:
            self.mark(login, heard + MARKED)
        self.assertEqual(self.parked(), {"default": True, "second": True})
        record = record or ((result, AFTER), (answer, ANSWERED))
        self.stop(seat, *(entry(heard + at) for entry, at in record),
                  last_assistant_message=WORDS)

    def test_a_result_after_the_refusals_unparks_that_login_alone(self):
        self.ran()
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_result_the_answer_is_not_yet_written_after_does_the_same(self):
        self.ran((result, AFTER))
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_result_before_the_refusals_leaves_them(self):
        self.ran((result, BEFORE), (answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_an_answer_no_result_came_before_leaves_them(self):
        self.ran((answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_the_owners_words_after_the_result_leave_them(self):
        self.ran((result, AFTER), (said, SAID), (answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_sidechains_result_alone_leaves_them(self):
        self.ran((sidechains, AFTER), (answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": True})


if __name__ == "__main__":
    unittest.main()
