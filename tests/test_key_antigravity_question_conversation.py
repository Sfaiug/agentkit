"""An Antigravity seat reads its question's answer from the conversation its own agy holds open.

agy's TUI cannot be handed an id for a new conversation, so a seat opened the usual way is given
none: it makes `<id>.db` in its store within seconds and holds it, its -wal and -shm open while
it runs, as agy 1.4.7 does.  Two seats in the same directory ask a question each; the owner's
reply, written later in one seat's conversation, answers that one, and the other's stands.
Black-box: seats opened by `ak orch` from a person's terminal on a fake agy, each conversation in
agy's own store under the Home; this test fails against `/bin/false`.
"""

import contextlib
import shlex
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akterm import Terminal

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NEW = ("--model", "gemini", "--workers", "gemini")    # a seat opened anew, on Antigravity
ASKED = {"acme": "Which schema should the acme parser write?",
         "beta": "Which branch should the acme banner land on?"}
# step_type and payload fields of an agy user input and of its model's answer, and the schema
# of its steps table as agy 1.2.13 wrote it
USER, MODEL = (14, 19, 2), (15, 20, 1)
STEPS = ("CREATE TABLE `steps` (`idx` integer,`step_type` integer NOT NULL DEFAULT 0,"
         "`status` integer NOT NULL DEFAULT 0,`metadata` blob,`step_payload` blob,"
         "PRIMARY KEY (`idx`))")

# agy: a TUI, the one call made on a terminal, that opens a conversation of its own, holds its
# database open in WAL mode as agy does, says its id to the test, and shows agy's prompt.
# Anything else fails, as offline.
AGY = """#!/bin/sh
[ -t 0 ] || exit 1
exec {python} {root}/agy.py {root}
"""
TUI = f"""import os, sqlite3, sys, uuid
from pathlib import Path
root, name = Path(sys.argv[1]), os.environ["AGENTKIT_SESSION"]
store = Path.home() / ".gemini/antigravity-cli/conversations"
store.mkdir(parents=True, exist_ok=True)
conversation = str(uuid.uuid4())
db = sqlite3.connect(store / f"{{conversation}}.db", isolation_level=None)
db.execute("PRAGMA journal_mode=WAL")
db.execute({STEPS!r})
(root / f"{{name}}.conversation").write_text(conversation)
sys.path.insert(0, {str(FIXTURES)!r})
import akpane
akpane.main(root / "prompt.txt", root / f"{{name}}.typed", ">")
"""


def varint(value):
    out = b""
    while True:
        byte, value = value & 0x7F, value >> 7
        if not value:
            return out + bytes([byte])
        out += bytes([byte | 0x80])


def nested(field, data):
    return varint(field << 3 | 2) + varint(len(data)) + data


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AntigravityQuestionConversation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        root = cls.home.root
        cls.home.fake("agy", AGY.format(root=shlex.quote(str(root)),
                                        python=shlex.quote(sys.executable)))
        (root / "agy.py").write_text(TUI)
        cls.home.write(".gemini/antigravity-cli/antigravity-oauth-token",
                       {"token": {"refresh_token": "acme"}})
        (root / "prompt.txt").write_text((FIXTURES / "antigravity-prompt-pane.txt").read_text())

    def launch(self, name):
        """Open an Antigravity seat as a person does, and the conversation its agy opened."""
        said = self.home.root / f"{name}.conversation"
        term = Terminal(self.home, "orch", name, *NEW, size=(120, 40))
        deadline = time.monotonic() + 60
        while not said.exists() or not said.read_text():
            if time.monotonic() > deadline:
                raise AssertionError(f"no agy started for {name}; the terminal shows:\n"
                                     f"{term.screen()}")
            time.sleep(0.05)
        return said.read_text()

    def said(self, conversation, text, at, kind=USER):
        """The owner typed `text` into that conversation at `at`, as agy records a user input, or
        its model answered it (MODEL)."""
        seconds, fraction = divmod(at, 1)
        stamp = varint(1 << 3) + varint(int(seconds)) + varint(2 << 3) + varint(
            round(fraction * 1e9))
        step, field, inner = kind
        payload = varint(1 << 3) + varint(step) + nested(field, nested(inner, text.encode()))
        path = self.home.path / ".gemini/antigravity-cli/conversations" / f"{conversation}.db"
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO steps (idx, step_type, status, metadata, step_payload)"
                       " VALUES ((SELECT COUNT(*) FROM steps), ?, 3, ?, ?)",
                       (step, nested(1, stamp), payload))

    def standing(self, name):
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        return ASKED[name] in done.out

    def test_a_reply_in_its_own_conversation_answers_only_its_question(self):
        conversations = {name: self.launch(name) for name in ASKED}
        self.assertNotEqual(conversations["acme"], conversations["beta"])
        for name, question in ASKED.items():
            done = self.home.ak("notify", "needs", question, "--session", name)
            self.assertEqual(done.code, 0, done.err)
            self.said(conversations[name], question, time.time(), MODEL)
        self.assertTrue(all(self.standing(name) for name in ASKED))

        self.said(conversations["acme"], "Write the v2 schema.", time.time())
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse(self.standing("acme"), "the owner's reply left its question standing")
        self.assertTrue(self.standing("beta"), "another seat's reply answered its question")


if __name__ == "__main__":
    unittest.main()
