"""`ak orch check SEAT` gives its model each answer the owner gave on an Antigravity seat's own
question card, beside the question and the choices the seat offered: the label of the choice
they picked, or the words they wrote in.  A card they skipped with Esc answers nothing.

agy 1.5.2 keeps a card in the conversation's database as a step holding the card as asked and as
answered, laid out as a real conversation captured on 7 Nov 2026 held it (`card`).  The seat's
conversation holds three: one the owner answered with a pick, one with a write-in, one they
skipped.  The model's turn hands in its gaps only where its workspace holds both answered
questions, their choices and answers, and not the skipped card's question: one quoting each
answer, kept, and one quoting the skipped question, which only the model wrote down, dropped.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
seat of tests/fixtures/akseat.py, with a fake harness of fakeadapter.py for the model.
"""

import contextlib
import shlex
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

CONVERSATION = "conv-acme"
PICKED = ("Which colour should the acme banner be?",
          ["Red (Make the acme banner red.)", "Blue (Make the acme banner blue.)"])
WRITTEN = ("Which font should the acme banner use?",
           ["Serif (Set the acme banner in serif.)", "Mono (Set the acme banner in mono.)"])
SKIPPED = ("Which size should the acme banner be?",
           ["Small (Make the acme banner small.)", "Large (Make the acme banner large.)"])
PICK, WRITE_IN = PICKED[1][1], "Sans, and make the text bold"
# the schema of agy's steps table, as agy 1.2.13 wrote it
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


def stamp(at):
    return number(1, at) + number(2, 250_000_000)


def card(asked, at, *, picked=None, written=None):
    """An `ask_question` card's step (step_type, metadata, step_payload), asked at `at` and
    answered a minute later with the id of the choice `picked`, the words `written`, or
    neither, as Esc leaves it."""
    question, choices = asked
    shown = nested(1, question.encode()) + b"".join(
        nested(2, nested(1, str(n).encode()) + nested(2, label.encode()))
        for n, label in enumerate(choices, 1))
    answered = shown + (nested(4, str(picked).encode()) if picked else b"") + (
        nested(5, written.encode()) if written else b"")
    read = choices[picked - 1] if picked else written
    metadata = (nested(1, stamp(at)) + nested(4, nested(2, b"ask_question"))
                + nested(8, stamp(at + 60)))
    payload = number(1, 132) + nested(147, nested(1, nested(22, nested(1, shown)))
                                      + nested(2, nested(22, nested(1, answered)))) + (
        nested(140, nested(2, nested(1, f"A1: {read}".encode()))) if read else b"")
    return 132, metadata, payload


class CardAnswersAntigravity(unittest.TestCase):
    def test_an_antigravity_seat_s_picks_and_write_ins_are_the_owner_s(self):
        with Home() as home:
            fake = fakeadapter.install(home, antigravity="pass", claude="pass")["claude"]
            Seat(home, "acme", model="gemini", alive=False,
                 record={"conversation": CONVERSATION})
            store = home.path / ".gemini/antigravity-cli/conversations" / f"{CONVERSATION}.db"
            store.parent.mkdir(parents=True)
            with contextlib.closing(sqlite3.connect(store)) as db, db:
                db.execute(STEPS)
                db.executemany("INSERT INTO steps (idx, step_type, status, metadata,"
                               " step_payload) VALUES (?, ?, 3, ?, ?)", [
                                   (n, *step) for n, step in enumerate([
                                       card(PICKED, 1_762_480_000, picked=2),
                                       card(WRITTEN, 1_762_480_600, written=WRITE_IN),
                                       card(SKIPPED, 1_762_481_200)])])
            akconfig.write(home, ["gemini", "opus"], extra='[done_check]\nmodel = "opus"')
            # no gap at all unless the workspace holds both answered questions, their choices
            # and the write-in, and nothing of the skipped card; then the model writes that
            # card's question down itself, a quote no answer of the owner's holds
            sh = [f"grep -rqF -- {shlex.quote(given)} . || exit 1"
                  for given in (*PICKED[1], *WRITTEN[1], PICKED[0], WRITTEN[0], WRITE_IN)]
            sh += [f"! grep -rqF -- {shlex.quote(SKIPPED[0])} . || exit 1",
                   f"echo {shlex.quote(SKIPPED[0])} > notes.md"]
            sh += [f"grep -rlF -- {shlex.quote(quote)} . | head -n 1 | while read -r file; do "
                   f"{shlex.quote(AK)} hand-in finding \"$file:1\" 'not in the work' "
                   f"'the owner asked for it' --quote {shlex.quote(quote)}; done"
                   for quote in (PICK, WRITE_IN, SKIPPED[0])]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(f'the owner: "{PICK}"', done.out)
            self.assertIn(f'the owner: "{WRITE_IN}"', done.out)
            self.assertNotIn(SKIPPED[0], done.out + done.err)
            self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
