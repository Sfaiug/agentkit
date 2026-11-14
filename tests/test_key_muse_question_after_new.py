"""A Muse seat follows its conversation through Muse's own `/new`.

`/new` fires no hook: the SessionStart hooks on a launch's line ran in the session it opened and
not in the next.  The next turn's end does, its Stop naming the session it ran in, and the seat
goes on there.  A question asked there, then the owner's reply written in that new session's
store, answers it; another seat in the same directory, its own Muse in its own session, keeps its
question; and the seat reopens on the new session.  An Esc's Interrupt, which Muse runs beside
the turn and may hand on again or after a later Stop, moves the seat nowhere: a session whose
turn the owner interrupted is kept once as one the seat left, for its done check, and the seat
still reopens on its last Stop's.  A line ak typed before the launch named its session went into
the session that launch reported, so once the seat has reopened the owner's same words in the new
session are the owner's, and answer a question asked there.  Black-box: seats opened by `ak orch`
from a person's terminal on a fake muse that fires each hook its line carries as Muse 1.4.12
does -- its own child, `sh -c`, the event's JSON on stdin, none of the seat's environment -- and
writes its session as Muse does, under the Home (tests/fixtures/musetui.py); this test fails
against `/bin/false`.
"""

import json
import sys
import time
import uuid
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import musetui
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akterm import Terminal

NEW = ("--model", "spark", "--workers", "spark")    # a seat opened anew, on Muse
ASKED = {"acme": "Which layout should the acme dashboard take?",
         "beta": "Which branch should the acme banner land on?"}
AGAIN = "Which font should the acme dashboard use?"     # acme's question once it has reopened
LINE = "Continue the interrupted turn."     # ak's, typed before acme's launch named its session
DAY = ".local/share/muse/sessions/2026/10/24"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class MuseQuestionAfterNew(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        musetui.install(cls.home)

    def launch(self, name, *opening):
        """Open a Muse seat as a person does: what its muse said it opened, once it has."""
        term = Terminal(self.home, "orch", name, *opening, size=(120, 40))
        try:
            return musetui.started(self.home, name)
        except AssertionError:
            raise AssertionError(f"no muse started for {name}; the terminal shows:\n"
                                 f"{term.screen()}") from None

    def new(self, name, prompt, ended="Stop"):
        """The owner types `/new` and then `prompt`: the same Muse opens another session, and no
        hook runs until that prompt's turn ends, or the owner's Esc ends it."""
        session = str(uuid.uuid4())
        self.said(session, prompt, time.time() - 30)
        musetui.stop(self.home, name, session, ended)
        return session

    def said(self, session, text, at, event=None):
        """That session's user typed `text` at `at`, as Muse records a prompt, or said `event`."""
        log = self.home.path / DAY / session / "session.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        line = {"schema_version": 1, "stream": {"kind": "session", "id": session},
                "record_type": "event", "recorded_at": round(at * 1_000_000),
                "payload": {"kind": "run", "run_id": uuid.uuid4().hex,
                            "event": event or {"kind": "started", "prompt": text}}}
        with log.open("a") as fh:
            fh.write(json.dumps(line) + "\n")

    def ask(self, name, question, session):
        """That seat asks the owner `question`, its words in `session`: in its chat before it
        stands, so no tick meanwhile types it back as left out of the chat."""
        self.said(session, question, time.time(),
                  {"kind": "assistant_message_committed", "text": question})
        done = self.home.ak("notify", "needs", question, "--session", name)
        self.assertEqual(done.code, 0, done.err)

    def standing(self, name, question=None):
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        return (question or ASKED[name]) in done.out

    def test_a_reply_after_new_answers_its_question_and_the_seat_reopens_there(self):
        muses = {name: self.launch(name, *NEW) for name in ASKED}
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        # its receipt first, as ak writes one before the launch names its session: that
        # launch's evidence in place of a conversation
        with (self.home.path / ".agentkit/state/input-acme.jsonl").open("a") as fh:
            fh.write(json.dumps({"at": time.time(), "text": LINE, "source": "ak",
                                 "harness": "muse", "conversation": None, "after": 0,
                                 "launch": {"muse_launch": record["muse_launch"]}}) + "\n")
        self.said(muses["acme"]["session"], LINE, time.time())
        session = self.new("acme", "Lay out the acme dashboard.")
        for name, question in ASKED.items():
            self.ask(name, question, session if name == "acme" else muses[name]["session"])
        self.assertTrue(all(self.standing(name) for name in ASKED))

        self.said(session, "Wide.", time.time())
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse(self.standing("acme"), "the owner's reply after /new left it standing")
        self.assertTrue(self.standing("beta"), "another seat's reply answered its question")

        escaped = self.new("acme", "Draw the acme chart.", "Interrupt")
        for late in (escaped, session):     # handed on again, and after its own turn's Stop
            musetui.stop(self.home, "acme", late, "Interrupt")
        done = self.home.tmux("kill-session", "-t", "=acme")
        self.assertEqual(done.code, 0, done.err)
        argv = self.launch("acme")["argv"]
        self.assertEqual(argv[argv.index("resume") + 1], session,
                         f"the seat reopened elsewhere than its last Stop's session: {argv}")
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        self.assertEqual([was["conversation"] for was in record["left"]],
                         [muses["acme"]["session"], escaped],
                         "the session an Esc ended is not kept once for the seat's done check")

        self.ask("acme", AGAIN, session)
        self.assertTrue(self.standing("acme", AGAIN))
        self.said(session, LINE, time.time())
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        # answered, so neither standing nor typed back into the seat as left out of the chat
        self.assertFalse(self.standing("acme", AGAIN))
        typed = self.home.root / "acme.typed.lines"
        self.assertNotIn(AGAIN, typed.read_text() if typed.exists() else "",
                         "ak's line before /new hid the owner's same words after it")


if __name__ == "__main__":
    unittest.main()
