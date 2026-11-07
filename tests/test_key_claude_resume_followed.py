"""A Claude seat follows the conversation its owner resumes in its screen, and keeps the one it
left for its done check, as it does across /clear.

In conversation A the owner asks for a retry button and a receipt email; the plan holds the
button alone, every line done.  The seat's Claude then resumes B, an earlier conversation of the
seat's directory no other seat names, where the owner says only "thanks".  The seat does not
read done, `ak orch check` names the email, quoting the owner, from a workspace holding A and B,
and reopening the seat resumes B.  A resume back to A leaves the check reading each once; a
resume onto a conversation another seat's record names, as its own or as one it left, leaves the
seat where it was.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a Claude seat of tests/fixtures/akseat.py whose transcripts the test
writes, with a fake harness of fakeadapter.py for the model.  The resume is Claude Code's
(2.1.319): in the seat's pane, a fake `claude` fires each SessionStart hook its adapter
registered (tests/fixtures/hookdrive.py) with `"source": "resume"` and the resumed conversation.
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

A = "5b8e2d14-7c3a-4f69-9e1d-2a6c8f0b4d37"
B = "c41f7a93-2e6b-4d8c-a5f0-9b3e1d7c2a68"
OWN = "8d2e4f60-1a3b-4c5d-9e7f-0b1c2d3e4f5a"     # beta's conversation
LEFT = "3f5a7c9e-2b4d-4f6a-8c0e-1d3f5a7b9c2e"    # one beta left
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
THANKS = "thanks"
PLANNED = "The upload page has a retry button"
# Claude Code in the seat's pane, as far as /resume goes: each SessionStart hook its settings
# register, fired with the resumed conversation, then the screen it shows
CLAUDE = '#!/bin/sh\n{fire}\ntouch {resumed}\nexec "$@"\n'


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ClaudeResumeFollowed(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        akconfig.write(home, ["opus"], extra='[done_check]\nmodel = "opus"')
        self.seat = seat = Seat(home, "acme", record={"conversation": A})
        # in the seat's directory too, so only its record keeps acme off its conversations
        Seat(home, "beta", cwd=seat.cwd, alive=False, record={
            "conversation": OWN, "left": [{"harness": "claude", "conversation": LEFT}]})
        self.folder = home.path / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.said(A, "2026-11-05", FIRST, SECOND)
        self.said(B, "2026-11-04", THANKS)
        home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                   "written 2026-11-05 10:05 · done 0123456789ab\n")
        self.checked = self.fake.dir / "checked.md"
        self.gap = {"sh": f"cp conversation.md {shlex.quote(str(self.checked))}; "
                          f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- "
                          f"{shlex.quote(SECOND)} . | head -n 1):1\" 'no receipt email' "
                          f"'the owner asked for it' --quote {shlex.quote(SECOND)}",
                    "final": "Checked.", "hand_in": [["done"]]}
        self.resume(B)
        self.assertEqual(self.record()["conversation"], B, "the resume did not move the seat")

    def said(self, conversation, day, *texts):
        turns = []
        for text in texts:
            turns += [{"type": "user", "message": {"role": "user", "content": text}},
                      {"type": "assistant", "message": {"role": "assistant", "content": [
                          {"type": "text", "text": "Done."}]}}]
        self.home.write(str((self.folder / f"{conversation}.jsonl").relative_to(self.home.path)),
                        "".join(json.dumps({**turn, "timestamp": f"{day}T10:{n:02d}:00Z"}) + "\n"
                                for n, turn in enumerate(turns)))

    def record(self):
        return json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())

    def resume(self, conversation):
        """The seat's Claude resumes that conversation of its directory, in its pane."""
        home, seat = self.home, self.seat
        payload = home.write(f"resume-{conversation}.json", {
            "hook_event_name": "SessionStart", "source": "resume", "session_id": conversation,
            "transcript_path": str(self.folder / f"{conversation}.jsonl")})
        resumed = home.root / f"resumed-{conversation}"
        claude = home.root / "claude" / "claude"
        claude.parent.mkdir(exist_ok=True)
        claude.write_text(CLAUDE.format(resumed=shlex.quote(str(resumed)), fire="\n".join(
            f"sh -c {shlex.quote(command)} < {shlex.quote(str(payload))}"
            for command in Hooks(home).commands("SessionStart"))))
        done = home.tmux("respawn-pane", "-k", "-t", seat.pane, "-e", "AGENTKIT_SESSION=acme",
                         "sh", str(claude), sys.executable, str(PANE), str(seat.screen_file),
                         str(seat.typed_file), seat.composer)
        self.assertEqual(done.code, 0, done.err)
        until = time.monotonic() + 30
        while not resumed.exists():
            self.assertLess(time.monotonic(), until, "the seat's Claude never resumed")
            time.sleep(0.05)
        seat.show("claude-prompt-pane.txt")

    def assert_found_reading_each_once(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], "acme  done")
        self.fake.behave(self.gap)
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        read = self.checked.read_text()
        self.assertEqual((read.count(SECOND), read.count(f" {THANKS}\n")), (1, 1), read)

    def test_the_owner_s_words_in_the_conversation_left_owe_a_check_that_finds_the_gap(self):
        self.assert_found_reading_each_once()

    def test_reopening_the_seat_resumes_the_conversation_it_resumed(self):
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        done = self.home.ak("orch", "acme", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        # the adapter is handed the conversation to open, and no `new`: one to resume
        # (`interactive <model> <effort> [session-id [new]]`)
        self.assertEqual(self.fake.calls("interactive")[-1]["argv"][2:], [B])

    def test_a_resume_back_to_the_conversation_left_reads_each_once(self):
        self.resume(A)
        self.assertEqual(self.record()["conversation"], A)
        self.assert_found_reading_each_once()

    def test_a_resume_onto_another_seat_s_conversation_leaves_the_seat_where_it_was(self):
        for conversation in (OWN, LEFT):
            with self.subTest(conversation=conversation):
                self.resume(conversation)
                self.assertEqual(self.record()["conversation"], B)


if __name__ == "__main__":
    unittest.main()
