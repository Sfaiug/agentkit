"""Claude's plugin says when a conversation's last request to its model went out.

Claude Code sends a request only once every result the model's message before it asked for is
written down, so a tool's result standing between two of the model's messages dates the later
one's request.  A result standing between two entries of one message, one of its own tools',
dates none.  Each transcript is written where Claude Code keeps it for the checkout /acme in a
Home of tests/fixtures/akbin.py, every entry dated by hand, and a child python3 asks the plugin;
a line the read reaches and cannot read says nothing.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

REPO = Path(__file__).resolve().parents[1]
TRANSCRIPT = ".claude/projects/-acme/conv-acme.jsonl"     # Claude Code's, for /acme's conversation
OPUS = "claude-opus-5-5"
# A caller of the plugin named: its answer for /acme's conversation, as JSON.  With a word after
# the name, the file goes between `transcript` naming it and the open; exit 3 where it raised.
ASK = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
from agentkit import harness
from agentkit.harness import claude

named = claude.transcript


def gone(*args):
    path = named(*args)
    os.remove(path)
    return path


claude.transcript = gone if sys.argv[3:] else named
try:
    print(json.dumps(harness.load(sys.argv[2]).last_sent({"cwd": "/acme"}, "/acme", "conv-acme")))
except OSError:
    sys.exit(3)
"""


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
        self.home = Home()
        self.addCleanup(self.home.close)
        self.path = self.home.path / TRANSCRIPT
        self.path.parent.mkdir(parents=True)

    def ask(self, *argv, code=0):
        done = self.home.run(sys.executable, "-c", ASK, str(REPO), *(argv or ["claude"]))
        self.assertEqual(done.code, code, done.err)
        return json.loads(done.out) if code == 0 else None

    def sent(self, *lines, gone=()):
        """`last_sent` of a transcript of those lines: entries, or raw bytes written as they are."""
        self.path.write_bytes(b"".join((line if isinstance(line, bytes)
                                        else json.dumps(line).encode()) + b"\n" for line in lines))
        return self.ask("claude", *gone)

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
        self.assertIsNone(self.ask())
        self.assertIsNone(self.sent(ASKING, result(2000), model(3000), gone=["gone"]))

    def test_a_file_it_cannot_read_back_is_no_line_it_refuses(self):
        # a pipe cannot be read from its end: io.UnsupportedOperation, an OSError and a ValueError
        os.mkfifo(self.path)
        writer = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)     # so opening it waits for none
        self.addCleanup(os.close, writer)
        self.ask(code=3)

    def test_a_plugin_without_its_own_says_nothing(self):
        self.assertIsNone(self.ask("codex"))


if __name__ == "__main__":
    unittest.main()
