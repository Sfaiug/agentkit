"""A question a seat with no blocking Stop leaves out of its chat is sent back there, once a stop.

A Muse, OpenCode or Antigravity seat's question reads `needs you` once its turn stopped on a
closing message holding it: the newest in its harness's own store, and the model's, never an
earlier one, a tool's output or the composer.  Until then it reads `working`, each stop that
left it out sent ak's reminder once, never over the owner's draft; a standing question left out
by a turn ak opened goes back too.  Black-box: `AK_BIN` through tests/fixtures/akbin.py, before
seats of tests/fixtures/akseat.py whose hooks fire as their harness fires them.
"""

import contextlib
import json
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, hookdrive
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat
from test_key_antigravity_question_conversation import nested, varint

QUESTION = "Which schema should the acme parser write? Options: v1 · v2"
TOKEN = "0" * 32
# each harness's model, its composer, that row empty and holding a draft, and the seat's
# conversation: Muse's and OpenCode's named by their launch's receipt
SEATS = {"muse": ("spark", "❯", "\n❯\n", "\n❯ {}\n", "muse-acme"),
         "antigravity": ("gemini", ">", "\n>\n", "\n> {}\n", "conv-antigravity"),
         "opencode": ("mimo", "┃", '┃  Ask anything… "What is the tech stack of this project?"',
                      "┃  {}", "ses_acme")}
STORES = {"muse": (".local/share/muse/sessions/2026/10/26/muse-acme/session.jsonl", None),
          "opencode": (".local/share/opencode/opencode.db", "CREATE TABLE session_message (id"
                       " text, session_id text, type text, seq integer, time_created integer,"
                       " time_updated integer, data text)"),
          "antigravity": (".gemini/antigravity-cli/conversations/conv-antigravity.db",
                          "CREATE TABLE steps (idx integer, step_type integer, status integer,"
                          " metadata blob, step_payload blob)")}


class Talk:
    """A seat's conversation in its harness's own store under the Home."""

    def __init__(self, home, harness):
        self.harness, self.users = harness, 0
        self.path = home.path / STORES[harness][0]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if STORES[harness][1]:
            self.row(STORES[harness][1])

    def row(self, sql, *values):
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            db.execute(sql, values)

    def user(self, text):
        self.users += 1
        self.add("user", text)

    def model(self, closing):
        """The model's closing message, after an earlier one and a tool's output that asked."""
        for who, text in (("model", QUESTION), ("tool", QUESTION), ("model", closing)):
            self.add(who, text)

    def add(self, who, text):
        at = time.time()
        if self.harness == "muse":
            event = {"user": {"kind": "started", "prompt": text},
                     "model": {"kind": "assistant_message_committed", "text": text},
                     "tool": {"kind": "tool_result_batch_committed", "results": [{"text": text}]}}
            with self.path.open("a") as fh:
                fh.write(json.dumps({"record_type": "event", "recorded_at": round(at * 1e6),
                                     "payload": {"kind": "run", "event": event[who]}}) + "\n")
        elif self.harness == "opencode":
            part = {"type": "tool", "state": {"content": [{"type": "text", "text": text}]}}
            data = ({"text": text} if who == "user" else
                    {"content": [part if who == "tool" else {"type": "text", "text": text}]})
            self.row("INSERT INTO session_message VALUES ('m', 'ses_acme', ?, (SELECT COUNT(*)"
                     " FROM session_message), ?, 0, ?)", "user" if who == "user" else
                     "assistant", round(at * 1000), json.dumps(data))
        else:
            stamp = varint(1 << 3) + varint(int(at)) + varint(2 << 3) + varint(int(at % 1 * 1e9))
            kind, field = {"user": (14, nested(19, nested(2, text.encode()))),
                           "model": (15, nested(20, nested(1, text.encode()))),
                           "tool": (21, nested(28, nested(1, text.encode())))}[who]
            self.row("INSERT INTO steps VALUES ((SELECT COUNT(*) FROM steps), ?, 3, ?, ?)",
                     kind, nested(1, stamp), varint(1 << 3) + varint(kind) + field)


class Seats:
    """A Muse, an OpenCode and an Antigravity seat that asked QUESTION; each owns its
    conversation unless `owned` is False."""
    owned = True

    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", *(model for model, *_ in SEATS.values())])
        self.seats, self.talks = {}, {}
        unowned = {"id_source": None, "conversation": None, "resumable": False}
        for harness, (model, composer, *_, conversation) in SEATS.items():
            launched = self.owned and harness != "antigravity" and home.write(
                f".agentkit/state/{harness}-launch-{TOKEN}/session", conversation)
            self.seats[harness] = Seat(home, harness, model=model, composer=composer,
                                       screen=f"{harness}-working-pane.txt", record=(
                                           {f"{harness}_launch": TOKEN, **unowned} if launched
                                           else {} if self.owned else unowned))
            self.talks[harness] = Talk(home, harness)
            self.talks[harness].user("Build the acme parser.")
            self.hook(harness, "UserPromptSubmit", prompt="Build the acme parser.")
            done = home.ak("notify", "needs", QUESTION, env={"AGENTKIT_SESSION": harness})
            self.assertEqual(done.code, 0, done.err)
        self.assertEqual(home.tick().code, 0)

    def hook(self, harness, event, **payload):
        if harness != "antigravity":         # it fires no hooks
            command = {"opencode": ("hooks/seat-state.sh",), "muse": ("adapters/muse.sh", "hook")}
            done = self.home.run("bash", str(hookdrive.ROOT / command[harness][0]),
                                 *command[harness][1:], env={"AGENTKIT_SESSION": harness},
                                 input=json.dumps({"hook_event_name": event, **payload}))
            self.assertEqual(done.code, 0, done.err)

    def stop(self, words, draft=None):
        """Each seat stops showing `words`, the owner's `draft` in its composer."""
        for harness, seat in self.seats.items():
            _model, composer, empty, typed, _ = SEATS[harness]
            # the pane wide enough for the reminder on one row and its cursor in the composer,
            # as the harness keeps its draft and its cursor in that box
            screen = (FIXTURES / f"{harness}-prompt-pane.txt").read_text().replace(
                "\n", f"{' ' * 320}\n  {words}\n", 1)
            screen = screen.replace(empty, typed.format(draft)) if draft else screen
            rows = screen.split("\n")
            at = max(row for row, text in enumerate(rows) if text.lstrip().startswith(composer))
            seat.show(f"{screen.removesuffix(chr(10))}\x1b[{at + 1};"
                      f"{rows[at].index(composer) + 3}H\n")
            self.hook(harness, "Stop", background_tasks=[])
        self.assertEqual(self.home.tick().code, 0)

    def reads(self, word, lines):
        """Every seat reads `word`, its pane given `lines` reminders in all."""
        for harness, seat in self.seats.items():
            with self.subTest(harness=harness):
                done = self.home.ak("orch", "why", harness)
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(done.out.splitlines()[0], f"{harness}  {word}", done.out)
                if word == "needs you":
                    self.assertIn(f"reason:    {QUESTION}\n", done.out)
                self.assertEqual(len(seat.lines()), lines, seat.lines())
                self.assertTrue(all(QUESTION in line for line in seat.lines()), seat.lines())

    def answer(self, words, closing, owner=False):
        """Each seat's next turn on the line ak typed last, or `words` of the owner's or of ak's
        own with its receipt as ak writes one, then its `closing` message."""
        for harness, talk in self.talks.items():
            line = self.seats[harness].lines()[-1] if words == "reminder" else words
            if words != "reminder" and not owner:
                with (self.home.path / f".agentkit/state/input-{harness}.jsonl").open("a") as fh:
                    fh.write(json.dumps({"at": time.time(), "text": words, "source": "ak",
                                         "harness": harness, "conversation": SEATS[harness][4],
                                         "after": talk.users}) + "\n")
            talk.user(line)
            self.hook(harness, "UserPromptSubmit", prompt=line)
            talk.model(closing)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class QuestionDeliveryAfterStop(Seats, unittest.TestCase):
    def test_a_question_left_out_goes_back_until_the_closing_message_holds_it(self):
        for talk in self.talks.values():
            talk.model("The acme parser is built.")
        self.stop("The acme parser is built.", draft=QUESTION)
        self.reads("working", 0)                # the owner's draft is theirs
        self.stop("The acme parser is built.")
        self.reads("working", 1)
        self.assertEqual(self.home.tick().code, 0)
        self.reads("working", 1)                # once a stop
        self.answer("reminder", QUESTION)
        self.stop(QUESTION)
        self.reads("needs you", 1)

        self.answer("run 20261026-0900-fix-api finished PASS", "Merged the parser.")
        self.stop("Merged the parser.")
        self.reads("working", 2)
        self.answer("reminder", QUESTION)
        self.stop(QUESTION)
        self.reads("needs you", 2)
        self.answer("v2.", "Writing v2.", owner=True)
        self.stop("Writing v2.")
        self.reads("idle", 2)                   # the owner's reply answered it

    def test_b_the_owners_reply_answers_a_question_left_out(self):
        for talk in self.talks.values():
            talk.model("The acme parser is built.")
        self.stop("The acme parser is built.")
        self.reads("working", 1)
        self.answer("v2.", "Writing v2.", owner=True)
        self.stop("Writing v2.")
        self.reads("idle", 1)


if __name__ == "__main__":
    unittest.main()
