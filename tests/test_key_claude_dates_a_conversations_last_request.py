"""Claude's plugin says when a conversation's last request to its model went out.

Claude Code sends a request only once every result the model's message before it asked for is
written down, so a tool's result standing between two of the model's messages dates the later
one's request.  A result standing between two entries of one message, one of its own tools',
dates none.  Each transcript is written where Claude Code keeps it for the checkout /acme in a
temporary home, every entry dated by hand; a line the read reaches and cannot read says nothing.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import harness
from agentkit.harness import claude

RECORD = {"cwd": "/acme"}
CONVERSATION = "conv-acme"
OPUS = "claude-opus-5-5"


def stamp(at):
    """A moment as Claude Code's transcripts write it."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def model(at, message="msg_answer", name=OPUS, **extra):
    return {"type": "assistant", "timestamp": stamp(at), **extra, "message": {
        "id": message, "role": "assistant", "model": name,
        "content": [{"type": "text", "text": "Working."}]}}


def result(at, **extra):
    return {"type": "user", "timestamp": stamp(at), **extra, "message": {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_acme", "content": "done"}]}}


ASKING = model(1000, "msg_asking")
PROMPT = {"type": "user", "timestamp": stamp(1500),
          "message": {"role": "user", "content": "Fix the API."}}
DEEP = b"[" * 100000 + b"]" * 100000        # deeper than json.loads follows
BROKEN = b'{"type": "user", "timestamp": '


class LastSent(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="ak-test-last-sent-")
        self.addCleanup(home.cleanup)
        held = patch.dict(os.environ, {"HOME": home.name})
        held.start()
        self.addCleanup(held.stop)
        self.path = claude.transcript_path(RECORD, CONVERSATION)
        self.path.parent.mkdir(parents=True)

    def sent(self, *lines):
        """`last_sent` of a transcript of those lines: entries, or raw bytes written as they are."""
        self.path.write_bytes(b"".join((line if isinstance(line, bytes)
                                        else json.dumps(line).encode()) + b"\n" for line in lines))
        return harness.load("claude").last_sent(RECORD, RECORD["cwd"], CONVERSATION)

    def test_a_result_before_the_answer_dates_its_request(self):
        self.assertEqual(self.sent(ASKING, result(2000), model(3000)), 2000)
        self.assertEqual(self.sent(ASKING, result(2000), result(2500), model(3000)), 2500)

    def test_a_result_inside_the_last_message_dates_nothing(self):
        self.assertEqual(self.sent(ASKING, result(2000), model(3000), result(3500), model(4000)),
                         2000)
        self.assertIsNone(self.sent(ASKING, model(3000), result(3500), model(4000)))

    def test_no_result_of_the_conversations_own_dates_it(self):
        self.assertIsNone(self.sent(ASKING, result(2000, isSidechain=True), model(3000)))
        self.assertIsNone(self.sent(ASKING, PROMPT, model(3000)))
        moved = result(2000)
        moved["timestamp"] = "soon"
        self.assertIsNone(self.sent(ASKING, moved, model(3000)))

    def test_a_line_the_read_reaches_and_cannot_read_says_nothing(self):
        for line in (DEEP, BROKEN, b"\r"):
            with self.subTest(line=line[:8]):
                self.assertIsNone(self.sent(ASKING, result(2000), line, model(3000)))
        self.assertEqual(self.sent(ASKING, result(2000), b"", model(3000)), 2000)
        for line in (DEEP, BROKEN):
            with self.subTest(before=line[:8]):
                self.assertEqual(self.sent(line, ASKING, result(2000), model(3000)), 2000)

    def test_a_synthetic_entry_after_the_answer_is_not_the_models(self):
        self.assertEqual(self.sent(ASKING, result(2000), model(3000),
                                   model(4000, "msg_synthetic", "<synthetic>")), 2000)

    def test_none_without_the_models_message_or_its_file(self):
        self.assertIsNone(self.sent(PROMPT, result(2000)))
        self.path.unlink()
        self.assertIsNone(harness.load("claude").last_sent(RECORD, RECORD["cwd"], CONVERSATION))
        named = claude.transcript

        def gone(*args):
            path = named(*args)
            Path(path).unlink()
            return path
        with patch.object(claude, "transcript", gone):
            self.assertIsNone(self.sent(ASKING, result(2000), model(3000)))

    def test_a_plugin_without_its_own_says_nothing(self):
        self.assertIsNone(harness.load("codex").last_sent(RECORD, RECORD["cwd"], CONVERSATION))


if __name__ == "__main__":
    unittest.main()
