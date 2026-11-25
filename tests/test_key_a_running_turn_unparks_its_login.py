"""A running turn unparks the login it ran on: a Stop judges the turn it ends by the later of its
start and its last request, which Claude Code sent once the tool's result standing before the
model's answer was written down.  A refusal made after the seat's prompt was heard and before
that result goes; one made after the result, or with no result before the answer to date the
request, stays, and a line the read cannot follow leaves the Stop answered as it would have been.

The Home, its seat and its refusals are tests/fixtures/unparking.py's.  Each refusal and each
entry is dated a whole number of seconds past the moment the prompt hook had been heard by.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.unparking import LOGINS, Unparking

BEFORE, MARKED, AFTER, ANSWERED = 1, 2, 3, 4     # seconds past the prompt hook
DEEP = b"[" * 100000 + b"]" * 100000             # deeper than json.loads follows


def stamp(at):
    """A moment as Claude Code's transcripts write it."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def result(at):
    return {"type": "user", "timestamp": stamp(at), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_acme", "content": "tests pass"}]}}


def answer(at):
    return {"type": "assistant", "timestamp": stamp(at), "message": {
        "id": "msg_answer", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": "The api is fixed and its tests pass."}]}}


class ARunningTurnUnparksItsLogin(Unparking):
    def ran(self, result_at=AFTER, deep=False, name="acme", marked=True):
        """A turn of seat `name` on the second login, both logins refused MARKED past its
        prompt where `marked`; its record then holds a tool's result dated `result_at` past it
        where that is not None, DEEP where `deep`, and the model's answer.  Its Stop's print."""
        seat = self.seat(name)
        self.prompt(seat)
        heard = time.time()     # the prompt hook dated the turn before this
        if marked:
            for login in LOGINS:
                self.mark(login, heard + MARKED)
            self.assertEqual(self.parked(), {"default": True, "second": True})
        said = [] if result_at is None else [result(heard + result_at)]
        if deep:
            said.append(DEEP)
        return self.stop(seat, *said, answer(heard + ANSWERED))

    def test_a_result_after_the_refusals_unparks_that_login_alone(self):
        self.ran()
        self.assertEqual(self.parked(), {"default": True, "second": False})

    def test_a_result_before_the_refusals_leaves_them(self):
        self.ran(BEFORE)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_an_answer_no_result_came_before_leaves_them(self):
        self.ran(None)
        self.assertEqual(self.parked(), {"default": True, "second": True})

    def test_a_line_the_read_cannot_follow_leaves_them_and_the_stop_as_ever(self):
        unmarked = self.ran(deep=True, name="plain", marked=False)
        marked = self.ran(deep=True)
        self.assertEqual(self.parked(), {"default": True, "second": True})
        self.assertEqual(marked.out, unmarked.out)


if __name__ == "__main__":
    unittest.main()
