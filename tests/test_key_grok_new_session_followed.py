"""A Grok Build seat follows the session its own process last ran a prompt in, whoever typed it,
and keeps each one it left for its done check.  In session A the owner asks for a retry button
and a receipt email; the plan holds the button alone, every line done.  They open B with /new and
say only "thanks".  The seat does not read done, `ak orch check` names the email from a workspace
holding A and B, and a reopen resumes B.  A prompt in A again leaves the check reading each once;
a line ak types itself (owed, typed by the tick) into the session shown moves the seat there; a
prompt in a session another seat's record names leaves it where it was.  Black-box on `AK_BIN`,
a fake model (fakeadapter.py), and in the seat's pane a fake `grok`, one process as 1.0.46's TUI,
firing its adapter's hooks as that TUI did on 7 Nov 2026: SessionStart on /new, UserPromptSubmit
and Stop on a prompt, naming its session and that session's updates.jsonl; /dashboard fires none.
"""

import json
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, Seat
from fixtures.hookdrive import Hooks

A = "5b8e2d14-7c3a-4f69-9e1d-2a6c8f0b4d37"
OWN, LEFT = "8d2e4f60-1a3b-4c5d-9e7f-0b1c2d3e4f5a", "3f5a7c9e-2b4d-4f6a-8c0e-1d3f5a7b9c2e"  # beta's
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
LINE = "Run 20261107-0900-fix-api passed and merged."     # a line ak owes the seat
# The TUI: each line entered is /new, a session of its own, or a prompt in the session SHOWING
# names.  Once every process its hooks started has ended, the line and its session go to HEARD.
GROK = r'''import json, os, subprocess, sys, threading, time, uuid
from pathlib import Path
from urllib.parse import quote
fixtures, showing, heard, *pane = sys.argv[1:]
sys.path.insert(0, fixtures)
import akpane
showing, heard, entered = Path(showing), Path(heard), Path(pane[1] + ".lines")
hooks = json.loads((Path.home() / ".grok/hooks/agentkit.json").read_text())["hooks"]

def fire(event, session, **fields):
    end, held = os.pipe()
    for hook in [hook for group in hooks.get(event, ()) for hook in group["hooks"]]:
        subprocess.run(["sh", "-c", hook["command"]], pass_fds=(held,), input=json.dumps({
            "hook_event_name": event, "session_id": session, "cwd": os.getcwd(),
            "transcript_path": str(updates(session)), **fields}).encode(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(held)
    with os.fdopen(end, "rb") as pipe:
        while pipe.read(4096):
            pass

def updates(session):
    return Path.home() / ".grok/sessions" / quote(os.getcwd(), safe="") / session / "updates.jsonl"

def said(session, kind, text):
    updates(session).parent.mkdir(parents=True, exist_ok=True)
    with updates(session).open("a") as out:
        out.write(json.dumps({"timestamp": time.time(), "method": "session/update", "params": {
            "sessionId": session, "update": {"sessionUpdate": kind, "_meta": {"promptIndex": 0},
                                             "content": {"type": "text", "text": text}}}}) + "\n")

def listen(seen):
    while True:
        for line in map(json.loads, entered.read_text().splitlines()[seen:]):
            seen, session = seen + 1, showing.read_text()
            if line == "/new":
                showing.write_text(session := str(uuid.uuid4()))
                fire("SessionStart", session, source="new")
            else:
                said(session, "user_message_chunk", line)
                fire("UserPromptSubmit", session, prompt=line)
                said(session, "agent_message_chunk", "Done.")
                fire("Stop", session, lastAssistantMessage="Done.")
            with heard.open("a") as out:
                out.write(json.dumps([line, session]) + "\n")
        time.sleep(0.05)

entered.touch()
threading.Thread(target=listen, args=(len(entered.read_text().splitlines()),), daemon=True).start()
akpane.main(*pane)
'''


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class GrokNewSessionFollowed(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, grokbuild="pass", claude="pass")
        self.fake, self.grok = fakes["claude"], fakes["grokbuild"]
        akconfig.write(home, ["grok", "opus"], extra='[done_check]\nmodel = "opus"')
        self.seat = seat = Seat(home, "acme", model="grok", screen="grok-prompt-pane.txt",
                                composer="│ ❯", record={"conversation": A})
        # in the seat's directory too, so only its record keeps acme off its sessions
        Seat(home, "beta", model="grok", cwd=seat.cwd, alive=False, record={
            "conversation": OWN, "left": [{"harness": "grokbuild", "conversation": LEFT}]})
        home.write(".agentkit/state/plan-acme.md", "- [x] The upload page has a retry button · "
                   "check: `true` · acme · written 2026-11-07 10:05 · done 0123456789ab\n")
        self.checked = self.fake.dir / "checked.md"
        self.gap = {"sh": f"cp conversation.md {shlex.quote(str(self.checked))}; "
                          f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- "
                          f"{shlex.quote(SECOND)} . | head -n 1):1\" 'no receipt email' "
                          f"'the owner asked for it' --quote {shlex.quote(SECOND)}",
                    "final": "Checked.", "hand_in": [["done"]]}
        Hooks(home, "grokbuild")
        grok = home.root / "grok"
        grok.write_text(GROK)
        self.showing, self.heard = home.root / "showing", home.root / "heard"
        self.showing.write_text(A)
        # keys typed before it takes its terminal are dropped, and its screen is the one drawn
        # already: its first frame is told by the title, which only it sets again
        self.assertEqual(home.tmux("select-pane", "-t", seat.pane, "-T", "").code, 0)
        done = home.tmux("respawn-pane", "-k", "-t", seat.pane, "-c", str(seat.cwd),
                         "-e", "AGENTKIT_SESSION=acme", sys.executable, str(grok), str(FIXTURES),
                         str(self.showing), str(self.heard), str(seat.screen_file),
                         str(seat.typed_file), seat.composer)
        self.assertEqual(done.code, 0, done.err)
        seat.show("grok-prompt-pane.txt")
        self.assertEqual([self.type(text) for text in (FIRST, SECOND)], [A, A])
        self.type("/new")
        self.b = self.type("thanks")
        self.assertNotEqual(self.b, A, "/new opened no session of its own")
        self.assertEqual(self.record()["conversation"], self.b, "the seat stayed on A")

    def record(self):
        return json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())

    def type(self, text):
        """The owner enters `text` in the seat's Grok: the session it went to, once answered."""
        before = self.heard.read_text().count("\n") if self.heard.exists() else 0
        for keys in (("-l", text), ("Enter",)):
            self.assertEqual(self.home.tmux("send-keys", "-t", self.seat.pane, *keys).code, 0)
        return self.answered(before)[1]

    def answered(self, before):
        """The line the seat's Grok answered after the `before` it had, and its session."""
        until = time.monotonic() + 120
        while not self.heard.exists() or self.heard.read_text().count("\n") <= before:
            self.assertLess(time.monotonic(), until, "the seat's Grok never answered")
            time.sleep(0.05)
        return json.loads(self.heard.read_text().splitlines()[before])

    def assert_found_reading_each_once(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], "acme  done")
        self.fake.behave(self.gap)
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        read = self.checked.read_text()
        self.assertEqual((read.count(SECOND), read.count(" thanks\n")), (1, 1), read)

    def test_the_owner_s_words_in_the_session_left_owe_a_check_that_finds_the_gap(self):
        self.assert_found_reading_each_once()

    def test_reopening_the_seat_resumes_the_session_it_went_to(self):
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        done = self.home.ak("orch", "acme", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        # the session to open and no `new`: one to resume (`interactive <model> <effort> [id [new]]`)
        self.assertEqual(self.grok.calls("interactive")[-1]["argv"][2:], [self.b])

    def test_a_prompt_back_in_the_session_left_reads_each_once(self):
        self.showing.write_text(A)
        self.assertEqual(self.type("Go on."), A)
        self.assertEqual(self.record()["conversation"], A)
        self.assertEqual([was["conversation"] for was in self.record()["left"]], [self.b])
        self.assert_found_reading_each_once()

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_line_ak_types_into_the_session_shown_moves_the_seat_there(self):
        self.showing.write_text(A)
        state = self.home.path / ".agentkit/state/seat-acme.json"
        state.write_text(json.dumps({**json.loads(state.read_text() if state.exists() else "{}"),
                                     "owed_lines": [{"line": LINE, "id": "4f2a9c1e7b3d5a80"}]}))
        # a collection on record from just now: one due would outlive the tick's box
        self.home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        before = self.heard.read_text().count("\n")
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.answered(before), [LINE, A])
        self.assertEqual(self.record()["conversation"], A)

    def test_a_prompt_in_another_seat_s_session_leaves_the_seat_where_it_was(self):
        for session in (OWN, LEFT):
            with self.subTest(session=session):
                self.showing.write_text(session)
                self.assertEqual(self.type("hello"), session)
                self.assertEqual(self.record()["conversation"], self.b)


if __name__ == "__main__":
    unittest.main()
