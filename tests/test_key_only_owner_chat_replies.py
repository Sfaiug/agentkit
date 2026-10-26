"""On Muse and Antigravity only the owner's own later reply answers a seat's chat question.

A seat asks with `ak notify needs` and works on, so its screen moves whether the owner answered,
only looked, or ak typed a line of its own into it: none of that is an answer.  Both harnesses
keep the owner's messages, dated, in their own conversation stores, and a message there written
after the question is: Muse's session log dates a line in microseconds (`recorded_at`), agy's
steps by a Timestamp in their metadata, seconds and nanoseconds, so a reply half a second after
the question, in the same second, answers it.  A reply whose date cannot be read leaves it
standing.

Each harness has two seats: one the owner opens at its prompt before its output, one opened
while it works.  Each tick then sees fresh output: after the open, after a line ak typed whose
words land in the conversation, after a reply with no readable date, and last after a real
reply.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
before seats of tests/fixtures/akseat.py, the owner opening one with `ak orch NAME` in a
terminal of tests/fixtures/akterm.py; each conversation is in its harness's store under the
Home, and each tick runs in `home.tick()`'s box.
"""

import contextlib
import json
import math
import sqlite3
import sys
import time
from pathlib import Path
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

QUESTION = "Which schema should the acme parser write?"
HANDBACK = "run 20261024-0900-fix-api finished"
# each harness's model, its composer, the screens a seat is opened on (at its prompt, working),
# and the fresh output each tick sees after
SCREENS = {"muse": ("spark", "❯", ("muse-prompt-pane.txt", "muse-working-pane.txt"),
                    ("muse-steering-pane.txt", "muse-compacting-pane.txt",
                     "muse-tall-line-pane.txt")),
           "antigravity": ("gemini", ">", ("antigravity-prompt-pane.txt",
                                           "antigravity-working-pane.txt"),
                           ("antigravity-background-pane.txt", "antigravity-usage-pane.txt",
                            "antigravity-tall-line-pane.txt"))}
# step_type and payload fields of an agy user input and of its model's answer, and the schema
# of its steps table as agy 1.2.13 wrote it
USER, MODEL = (14, 19, 2), (15, 20, 1)
STEPS = ("CREATE TABLE `steps` (`idx` integer,`step_type` integer NOT NULL DEFAULT 0,"
         "`status` integer NOT NULL DEFAULT 0,`metadata` blob,`step_payload` blob,"
         "PRIMARY KEY (`idx`))")


def varint(value):
    out = b""
    while True:
        byte, value = value & 0x7F, value >> 7
        if not value:
            return out + bytes([byte])
        out += bytes([byte | 0x80])


def number(field, value):
    return varint(field << 3) + varint(value)


def nested(field, data):
    return varint(field << 3 | 2) + varint(len(data)) + data


class Conversation:
    """A seat's conversation in its harness's own store under the Home."""

    def __init__(self, home, harness, conversation):
        self.harness, self.conversation = harness, conversation
        if harness == "muse":
            self.path = (home.path / ".local/share/muse/sessions/2026/10/24" / conversation
                         / "session.jsonl")
            self.path.parent.mkdir(parents=True)
            self.path.touch()
        else:
            self.path = home.path / ".gemini/antigravity-cli/conversations" / f"{conversation}.db"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.closing(sqlite3.connect(self.path)) as db, db:
                db.execute(STEPS)
        self.steps = 0

    def said(self, text, at, *, date=..., model=False):
        """The user side wrote `text` at `at`, and the model then its closing message, which
        repeats the question as a seat's must for it to stand (`model`: the model wrote `text`);
        `date`, where given, is what the store keeps as its date, None for nothing."""
        if self.harness == "muse":
            line = {"schema_version": 1, "stream": {"kind": "session", "id": "s"},
                    "sequence": self.steps, "record_type": "event",
                    "recorded_at": round(at * 1_000_000) if date is ... else date,
                    "payload": {"kind": "run", "run_id": f"r{self.steps}",
                                "event": {"kind": "assistant_message_committed", "text": text}
                                if model else {"kind": "started", "prompt": text}}}
            with self.path.open("a") as fh:
                fh.write(json.dumps(line) + "\n")
        else:
            seconds, fraction = divmod(at, 1)
            stamp = number(1, int(seconds)) + number(2, round(fraction * 1e9))
            metadata = nested(1, stamp) if date is ... else date
            kind, field, inner = MODEL if model else USER
            payload = number(1, kind) + nested(field, nested(inner, text.encode()))
            with contextlib.closing(sqlite3.connect(self.path)) as db, db:
                db.execute("INSERT INTO steps (idx, step_type, status, metadata, step_payload)"
                           " VALUES (?, ?, 3, ?, ?)", (self.steps, kind, metadata, payload))
        self.steps += 1
        if not model:
            self.said(QUESTION, time.time(), model=True)


def clients(home):
    return home.tmux("list-clients", "-F", "#{session_name}").out.split()


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class OnlyOwnerReplies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "spark", "gemini"])
        # the question is asked a quarter into a second, two minutes ago
        cls.asked = math.floor(time.time()) - 120 + 0.25
        cls.seats = {}
        for harness, (model, composer, opened, _output) in SCREENS.items():
            for when, screen in zip(("before", "during"), opened):
                name = f"{harness}-{when}"
                # a Muse seat's session is the one its launch's SessionStart hook reported
                token = uuid.uuid4().hex
                owned = ({"conversation": None, "id_source": None, "muse_launch": token}
                         if harness == "muse" else {})
                seat = Seat(home, name, model=model, composer=composer, screen=screen,
                            record=owned)
                talk = Conversation(home, harness, f"conv-{name}")
                if owned:
                    home.write(f".agentkit/state/muse-launch-{token}/session", talk.conversation)
                talk.said("Build the acme parser.", cls.asked - 60)
                home.write(f".agentkit/state/notify-{name}.json",
                           {"session": name, "kind": "needs", "text": QUESTION,
                            "time": cls.asked})
                cls.seats[name] = (harness, seat, talk)

    def open(self, name):
        """The owner opens that seat with `ak orch NAME`, and leaves it."""
        terminal = Terminal(self.home, "orch", name)
        deadline = time.monotonic() + 30
        while name not in clients(self.home):
            self.assertLess(time.monotonic(), deadline, terminal.screen())
            time.sleep(0.05)
        terminal.keys("C-b", "d")
        self.assertEqual(terminal.exit_code(), 0, terminal.screen())

    def output(self, step):
        """Every seat shows output it had not shown, and a tick looks at it."""
        for harness, seat, _talk in self.seats.values():
            seat.show(SCREENS[harness][3][step])
        self.tick()

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def standing(self):
        """The seats whose question still stands: back at its prompt, a seat says it there."""
        found = []
        for harness, seat, _talk in self.seats.values():
            seat.show(SCREENS[harness][2][0])
            done = self.home.ak("orch", "why", seat.name)
            self.assertEqual(done.code, 0, done.err)
            if QUESTION in done.out:
                found.append(seat.name)
        return found

    def test_only_a_later_reply_of_the_owners_answers(self):
        for name in self.seats:
            self.open(name)
        self.output(0)
        self.assertCountEqual(self.standing(), self.seats, "opening the seat answered it")

        # ak types a line into each seat, its receipt first as ak writes one; its words land
        # in the conversation, then output
        for harness, seat, talk in self.seats.values():
            self.home.write(f".agentkit/state/input-{seat.name}.jsonl",
                            json.dumps({"at": time.time(), "text": HANDBACK, "source": "ak",
                                        "harness": harness,
                                        "conversation": talk.conversation,
                                        "after": talk.steps // 2}) + "\n")
            talk.said(HANDBACK, time.time())
        self.output(1)
        self.assertCountEqual(self.standing(), self.seats, "ak's own line answered it")

        # a reply the store keeps no date for, or one ak cannot read: agy's seconds of now,
        # its nanoseconds cut off
        cut = nested(1, number(1, int(time.time())) + b"\x10\x80")
        for name, (harness, _seat, talk) in self.seats.items():
            talk.said("The first one.", time.time(), date=None if name.endswith("-before") else
                      "soon" if harness == "muse" else cut)
        self.output(2)
        self.assertCountEqual(self.standing(), self.seats, "a reply with no date answered it")

        # the owner's reply, half a second after the question, in the same second
        for _harness, _seat, talk in self.seats.values():
            talk.said("The second one.", self.asked + 0.5)
        self.tick()
        self.assertEqual(self.standing(), [])


if __name__ == "__main__":
    unittest.main()
