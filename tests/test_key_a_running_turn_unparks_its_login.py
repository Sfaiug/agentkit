"""A running turn unparks the login it ran on: a Stop judges the turn it ends by the later of its
start and the last request of the seat's own turn on its record (or the last tool's result outside
a sidechain where the record holds no request line), that answer's entry written yet or not.  A
refusal made after the seat's prompt was heard and before that request or result goes; one made
after it stays, and so does every one where no request of the seat's own turn or result outside a
sidechain stands after the owner's last words.  A line the read cannot follow leaves every one,
the Stop answered as with none made.

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


def request(at, source="repl_main_thread"):
    """A request to the model on Claude Code's record."""
    return {"type": "api-request", "timestamp": stamp(at), "querySource": source,
            "version": "2.1.332"}


def other_request(at):
    """A request line of another querySource."""
    return request(at, source="other")


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


def deep(_at):
    """A line nested deeper than json.loads follows, as its bytes are written."""
    return b"[" * 100000 + b"]" * 100000


def answer(at):
    return {"type": "assistant", "timestamp": stamp(at), "message": {
        "id": "msg_answer", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": WORDS}]}}


class ARunningTurnUnparksItsLogin(Unparking):
    def ran(self, *record, name="acme", marked=True):
        """A turn of seat `name` on the second login, both logins refused MARKED past its
        prompt where `marked`; its record then holds `record`, (a line of a moment, seconds past
        that prompt) each -- a tool's result after the refusals and the model's answer where
        none is given -- and its Stop hands over the model's last words, as Claude Code's does;
        what that Stop printed."""
        seat = self.seat(name)
        self.prompt(seat)
        heard = time.time()     # the prompt hook dated the turn before this
        if marked:
            for login in LOGINS:
                self.mark(login, heard + MARKED)
            self.assertEqual(self.parked(), {"default": True, "second": True})
        record = record or ((result, AFTER), (answer, ANSWERED))
        return self.stop(seat, *(line(heard + at) for line, at in record),
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

    def test_a_line_the_read_cannot_follow_leaves_them_and_the_stop_as_ever(self):
        record = (result, AFTER), (deep, AFTER), (answer, ANSWERED)
        unmarked = self.ran(*record, name="plain", marked=False)
        marked = self.ran(*record)
        self.assertEqual(self.parked(), {"default": True, "second": True})
        self.assertEqual(marked.out, unmarked.out)

    def test_a_refusal_before_the_last_request_goes(self):
        self.ran((result, BEFORE), (request, AFTER))
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_request_with_no_result_after_the_refusals_does_the_same(self):
        self.ran((request, AFTER), (answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_request_before_the_refusals_leaves_them(self):
        self.ran((result, BEFORE), (request, BEFORE), (answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_request_of_another_query_source_leaves_them(self):
        self.ran((result, BEFORE), (other_request, AFTER), (answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_the_owners_words_after_the_request_leave_them(self):
        self.ran((result, BEFORE), (request, AFTER), (said, SAID), (answer, ANSWERED))
        self.assertEqual(self.parked(), {"default": True, "second": True})


if __name__ == "__main__":
    unittest.main()
