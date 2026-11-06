"""A conversation a Claude seat's /clear leaves stays the seat's for its done check: the owner's
words there still owe a check, and the check reads them, under whichever name the seat goes by.

The owner asks for a retry button and a receipt email; the plan holds the button alone, every
line done.  The owner then clears the conversation and writes nothing in the new one.  The seat
does not read done, and `ak orch check` names the email, quoting the owner, after a rename too;
with the cleared conversation's transcript gone, as with a current one's, the owner said nothing.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
Claude seat of tests/fixtures/akseat.py whose transcript the test writes, with a fake harness of
fakeadapter.py for the model.  The clear is Claude Code's: in the seat's pane, a fake `claude`
fires each SessionStart hook its adapter registered (tests/fixtures/hookdrive.py) with the new
conversation, as tests/test_seat_follows_clear.py's hook does.
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
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks

BEFORE = "5b8e2d14-7c3a-4f69-9e1d-2a6c8f0b4d37"
AFTER = "c41f7a93-2e6b-4d8c-a5f0-9b3e1d7c2a68"
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
PLANNED = "The upload page has a retry button"
GAP = {"sh": f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- {shlex.quote(SECOND)} . | "
             f"head -n 1):1\" 'no receipt email' 'the owner asked for it' "
             f"--quote {shlex.quote(SECOND)}",
       "final": "Checked.", "hand_in": [["done"]]}
# Claude Code in the seat's pane, as far as /clear goes: each SessionStart hook its settings
# register, fired with the new conversation, then the screen it shows
CLAUDE = '#!/bin/sh\n{fire}\ntouch {cleared}\nexec "$@"\n'


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ClearedConversationChecked(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        akconfig.write(home, ["opus"], extra='[done_check]\nmodel = "opus"')
        self.seat = seat = Seat(home, "acme", record={"conversation": BEFORE})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        turns = []
        for text in (FIRST, SECOND):
            turns += [{"type": "user", "message": {"role": "user", "content": text}},
                      {"type": "assistant", "message": {"role": "assistant", "content": [
                          {"type": "text", "text": "Done."}]}}]
        self.before = home.write(f".claude/projects/{folder}/{BEFORE}.jsonl", "".join(
            json.dumps({**turn, "timestamp": f"2026-11-05T10:{n:02d}:00Z"}) + "\n"
            for n, turn in enumerate(turns)))
        home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                   "written 2026-11-05 10:05 · done 0123456789ab\n")
        payload = home.write("clear.json", {
            "hook_event_name": "SessionStart", "source": "clear", "session_id": AFTER,
            "transcript_path": str(home.path / f".claude/projects/{folder}/{AFTER}.jsonl")})
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

    def assert_owed_and_found(self, name):
        why = self.home.ak("orch", "why", name)
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], f"{name}  done")
        self.fake.behave(GAP)
        done = self.home.ak("orch", "check", name)
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)

    def test_the_owner_s_words_in_a_cleared_conversation_owe_a_check_that_finds_the_gap(self):
        self.assert_owed_and_found("acme")

    def test_a_renamed_seat_keeps_the_conversation_it_cleared(self):
        renamed = self.home.ak("orch", "rename", "acme", "quay")
        self.assertEqual(renamed.code, 0, renamed.out + renamed.err)
        self.assert_owed_and_found("quay")

    def test_a_cleared_conversation_whose_transcript_is_gone_holds_no_owner_words(self):
        self.before.unlink()
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.out.splitlines()[0], "acme  done", why.out + why.err)
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.fake.n, 0)


if __name__ == "__main__":
    unittest.main()
