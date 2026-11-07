"""A Claude seat's conversation outlives Claude Code deleting its transcript: once a tick has
given it ak's own name, the done check still reads what the owner said there.

Claude Code deletes a transcript nobody wrote to for 30 days (`cleanupPeriodDays`).  A Claude
seat's plan lines are all done; its owner asked it for a retry button and a receipt email, and its
plan holds the button alone.  After one tick (`ak watch`) and then the transcript's deletion, the
seat does not read done, and `ak orch check` names the email, quoting the owner, with the seat's
replies in its model's workspace too: so for the seat's conversation, and for one it left with
/clear before that tick, where the email was asked.  A transcript deleted before any tick holds
no owner words, as before.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
Claude seat of tests/fixtures/akseat.py whose transcript the test writes, with a fake harness of
fakeadapter.py for the model.  The clear is Claude Code's, as
tests/test_key_cleared_conversation_checked.py drives it: in the seat's pane, a fake `claude`
fires each SessionStart hook its adapter registered (tests/fixtures/hookdrive.py) with the new
conversation.
"""

import json
import re
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks

BEFORE = "3f6a9d21-8b4e-4c7a-9e05-6d2b1f8c4a79"
AFTER = "a82e5c47-1d9b-4f36-b7c0-5e4a2d9f8b13"
BUTTON = "Add a retry button to the upload page."
EMAIL = "Also email me a receipt after every upload."
REPLY = "A receipt email needs a mail provider; I will pick one once the button is in."
PLANNED = "The upload page has a retry button"
DONE = "acme  done"
# the model's turn: no gap at all unless its workspace holds the seat's reply
GAP = {"sh": f"grep -rqF -- {shlex.quote(REPLY)} . || exit 1; {shlex.quote(AK)} hand-in finding "
             f"\"$(grep -rlF -- {shlex.quote(EMAIL)} owner | head -n 1):1\" 'no receipt email' "
             f"'the owner asked for it' --quote {shlex.quote(EMAIL)}",
       "final": "Checked.", "hand_in": [["done"]]}
# Claude Code in the seat's pane, as far as /clear goes: each SessionStart hook its settings
# register, fired with the new conversation, then the screen it shows
CLAUDE = '#!/bin/sh\n{fire}\ntouch {cleared}\nexec "$@"\n'


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux, and bwrap able to box a tick")
class OwnerWordsKept(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        akconfig.write(home, ["opus"], extra='[done_check]\nmodel = "opus"')
        self.seat = Seat(home, "acme", record={"conversation": BEFORE})
        self.folder = re.sub(r"[^A-Za-z0-9]", "-", str(self.seat.cwd))
        turns = []
        for asked, answered in ((BUTTON, "Done: the upload page has a retry button."),
                                (EMAIL, REPLY)):
            turns += [{"type": "user", "message": {"role": "user", "content": asked}},
                      {"type": "assistant", "message": {"role": "assistant", "content": [
                          {"type": "text", "text": answered}]}}]
        self.transcript = home.write(f".claude/projects/{self.folder}/{BEFORE}.jsonl", "".join(
            json.dumps({**turn, "timestamp": f"2026-11-05T10:{n:02d}:00Z"}) + "\n"
            for n, turn in enumerate(turns)))
        home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                   "written 2026-11-05 10:05 · done 0123456789ab\n")

    def clear(self):
        """The owner clears the seat's conversation, and writes nothing in the new one."""
        home, seat = self.home, self.seat
        payload = home.write("clear.json", {
            "hook_event_name": "SessionStart", "source": "clear", "session_id": AFTER,
            "transcript_path": str(home.path / f".claude/projects/{self.folder}/{AFTER}.jsonl")})
        cleared = home.root / "cleared"
        claude = home.root / "claude" / "claude"
        claude.parent.mkdir()
        claude.write_text(CLAUDE.format(cleared=shlex.quote(str(cleared)), fire="\n".join(
            f"sh -c {shlex.quote(command)} < {shlex.quote(str(payload))}"
            for command in Hooks(home).commands("SessionStart"))))
        done = home.tmux("respawn-pane", "-k", "-t", seat.pane, "-e", "AGENTKIT_SESSION=acme",
                         "sh", str(claude), sys.executable, str(PANE), str(seat.screen_file),
                         str(seat.typed_file), seat.composer)
        self.assertEqual(done.code, 0, done.err)
        until = time.monotonic() + 30
        while not cleared.exists():
            self.assertLess(time.monotonic(), until, "the seat's Claude never cleared")
            time.sleep(0.05)
        seat.show("claude-prompt-pane.txt")
        record = json.loads((home.path / ".agentkit/state/session-acme.json").read_text())
        self.assertEqual(record["conversation"], AFTER, "the clear did not move the seat")

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def why(self):
        done = self.home.ak("orch", "why", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.splitlines()[0]

    def assert_owed_and_found(self):
        self.assertNotEqual(self.why(), DONE)
        self.fake.behave(GAP)
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(EMAIL, done.out)
        self.assertEqual(self.fake.n, 1)

    def test_a_ticked_transcript_claude_deleted_still_holds_the_owner_s_words(self):
        self.tick()
        self.transcript.unlink()
        self.assert_owed_and_found()

    def test_so_does_one_of_a_conversation_the_seat_cleared_before_the_tick(self):
        self.clear()
        self.tick()
        self.transcript.unlink()
        self.assert_owed_and_found()

    def test_a_transcript_deleted_before_any_tick_holds_no_owner_words(self):
        self.transcript.unlink()
        self.tick()
        self.assertEqual(self.why(), DONE)
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.fake.n, 0)


if __name__ == "__main__":
    unittest.main()
