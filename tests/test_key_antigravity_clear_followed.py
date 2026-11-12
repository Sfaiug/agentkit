"""An Antigravity seat follows the conversation its own agy last took a prompt in, and keeps each
one it left for its done check.  In conversation A the owner asks for a retry button and a
receipt email, nothing reading the seat meanwhile; the plan holds the button alone, every line
done.  They type /clear: agy holds A and B, then B alone once B took a prompt, and in B they say
only "thanks".  The seat does not read done, `ak orch check` names the email from a workspace
holding A and B once each, and once agy is gone a reopen resumes B.  A prompt naming a
conversation with no database in agy's store, or one another seat's record names, as its own or
as one it left, leaves the seat where it was.  Black-box on `AK_BIN`: the seat opened by `ak orch`
from a person's terminal through the shipped adapter, a fake model (fakeadapter.py) making the
check, and in the seat's pane a fake `agy`, one process as agy 1.5's TUI, keeping each
conversation as a database of agy's store and firing its launch's PreInvocation hooks on a
prompt, naming that conversation.
"""

import contextlib
import json
import shlex
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akpane import stamp
from fixtures.akseat import FIXTURES, Seat
from fixtures.akterm import Terminal
from fixtures.hookdrive import ROOT

FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
GHOST = "6c1d8e2f-4a7b-4e3c-9d5f-0b2a7c8e1f43"      # no database in agy's store
OWN, LEFT = "8d2e4f60-1a3b-4c5d-9e7f-0b1c2d3e4f5a", "3f5a7c9e-2b4d-4f6a-8c0e-1d3f5a7b9c2e"  # beta's
# the schema of agy's steps table, as agy 1.2.13 wrote it
STEPS = ("CREATE TABLE IF NOT EXISTS `steps` (`idx` integer,`step_type` integer NOT NULL"
         " DEFAULT 0,`status` integer NOT NULL DEFAULT 0,`metadata` blob,`step_payload` blob,"
         "PRIMARY KEY (`idx`))")
# The shipped adapter, from the directory of adapters the fake's install names, each call logged.
ADAPTER = """#!/bin/sh
{python} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >>{log}
exec bash {adapter} "$@"
"""
# agy's TUI, run on a terminal (any other call fails, as offline): it opens a new conversation,
# or the one `--conversation` names where its database is there, and holds its database open.
# Each line entered is /clear, which opens a new one and holds both, or a prompt in the
# conversation SHOWING names: its PreInvocation hooks fired with it, then, where agy holds that
# one, the prompt and an answer written there and every other one let go.  Once every process
# its hooks started has ended, the line and its conversation go to HEARD.
AGY = r'''
import json, os, sqlite3, subprocess, sys, threading, time, uuid
from pathlib import Path
if not sys.stdin.isatty():
    sys.exit(1)
sys.path.insert(0, FIXTURES)
import akpane
args, root = sys.argv[1:], Path(ROOT)
showing, heard, typed = root / "showing", root / "heard", root / "agy.typed"
entered = typed.with_name(typed.name + ".lines")
hooks = json.loads((Path(args[args.index("--add-dir") + 1]) / ".agents/hooks.json").read_text())
pre = [hook["command"] for agent in hooks.values() for hook in agent.get("PreInvocation", ())]
store = Path.home() / ".gemini/antigravity-cli/conversations"
store.mkdir(parents=True, exist_ok=True)
held = {}

def varint(value):
    out = b""
    while True:
        byte, value = value & 0x7F, value >> 7
        if not value:
            return out + bytes([byte])
        out += bytes([byte | 0x80])

def nested(field, data):
    return varint(field << 3 | 2) + varint(len(data)) + data

def hold(conversation):
    db = sqlite3.connect(store / f"{conversation}.db", isolation_level=None,
                         check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(STEPS)
    held[conversation] = db
    showing.write_text(conversation)

def said(db, step, field, inner, text):
    seconds, fraction = divmod(time.time(), 1)
    at = varint(1 << 3) + varint(int(seconds)) + varint(2 << 3) + varint(round(fraction * 1e9))
    db.execute("INSERT INTO steps (idx, step_type, status, metadata, step_payload)"
               " VALUES ((SELECT COUNT(*) FROM steps), ?, 3, ?, ?)",
               (step, nested(1, at), varint(1 << 3) + varint(step)
                + nested(field, nested(inner, text.encode()))))

def fire(line, conversation):
    end, kept = os.pipe()
    for command in pre:
        subprocess.run(["sh", "-c", command], pass_fds=(kept,), input=json.dumps({
            "invocationNum": 0, "lastUserInput": line, "conversationId": conversation}).encode(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(kept)
    with os.fdopen(end, "rb") as pipe:
        while pipe.read(4096):
            pass

def listen(seen):
    while True:
        for line in map(json.loads, entered.read_text().splitlines()[seen:]):
            seen += 1
            if line == "/clear":
                hold(str(uuid.uuid4()))
            else:
                conversation = showing.read_text()
                fire(line, conversation)
                if conversation in held:
                    said(held[conversation], 14, 19, 2, line)
                    said(held[conversation], 15, 20, 1, "Done.")
                    for other in [other for other in held if other != conversation]:
                        held.pop(other).close()
            with heard.open("a") as out:
                out.write(json.dumps([line, showing.read_text()]) + "\n")
        time.sleep(0.05)

if "--conversation" in args:
    resumed = args[args.index("--conversation") + 1]
    if not (store / f"{resumed}.db").is_file():
        sys.exit(1)
    hold(resumed)
else:
    hold(str(uuid.uuid4()))
entered.touch()
threading.Thread(target=listen, args=(len(entered.read_text().splitlines()),),
                 daemon=True).start()
akpane.main(root / "screen.txt", typed, ">")
'''


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AntigravityClearFollowed(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        root = home.root
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        self.adapter_log = root / "antigravity.calls"
        adapter = root / "adapters/antigravity.sh"
        adapter.write_text(ADAPTER.format(
            python=shlex.quote(sys.executable), log=shlex.quote(str(self.adapter_log)),
            adapter=shlex.quote(str(ROOT / "adapters/antigravity.sh"))))
        adapter.chmod(0o755)
        akconfig.write(home, ["gemini", "opus"], extra='[done_check]\nmodel = "opus"')
        home.write(".gemini/antigravity-cli/antigravity-oauth-token",
                   {"token": {"refresh_token": "acme"}})
        home.fake("agy", f"#!{sys.executable}\nROOT, FIXTURES, STEPS = {str(root)!r}, "
                         f"{str(FIXTURES)!r}, {STEPS!r}\n{AGY}")
        (root / "screen.txt").write_text((FIXTURES / "antigravity-prompt-pane.txt").read_text())
        self.showing, self.heard = root / "showing", root / "heard"
        # a seat whose agy is gone, its own conversation the one its launch saw, and one it left
        Seat(home, "beta", model="gemini", alive=False, record={
            "conversation": None, "id_source": None, "antigravity_launch": "beta-launch",
            "antigravity_open": {"launch": "beta-launch", "conversation": OWN},
            "left": [{"harness": "antigravity", "conversation": LEFT}]})
        for conversation in (OWN, LEFT):
            path = home.path / ".gemini/antigravity-cli/conversations" / f"{conversation}.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.closing(sqlite3.connect(path)) as db, db:
                db.execute(STEPS)
        term = Terminal(home, "orch", "acme", "--model", "gemini", "--workers", "gemini",
                        size=(120, 40))
        deadline = time.monotonic() + 60
        while not self.showing.exists() or not self.drawn():
            self.assertLess(time.monotonic(), deadline,
                            f"no agy started; the terminal shows:\n{term.screen()}")
            time.sleep(0.05)
        self.a = self.showing.read_text()
        # once the seat is open: a seat opened anew starts with no plan
        home.write(".agentkit/state/plan-acme.md", "- [x] The upload page has a retry button · "
                   "check: `true` · acme · written 2026-11-09 10:05 · done 0123456789ab\n")
        self.assertEqual([self.type(text) for text in (FIRST, SECOND)], [self.a, self.a])
        self.type("/clear")
        self.b = self.type("thanks")
        self.assertNotEqual(self.b, self.a, "/clear opened no conversation of its own")
        self.assertEqual(self.record()["conversation"], self.b, "the seat stayed on A")

    def drawn(self):
        """Whether the seat's agy has drawn its screen, its terminal taken: keys typed sooner are
        dropped (tests/fixtures/akpane.py)."""
        frame = stamp((self.home.root / "screen.txt").read_bytes(), 0).rsplit(" ", 1)[0]
        return self.home.tmux("display-message", "-p", "-t", "=acme:",
                              "#{pane_title}").out.rsplit(" ", 1)[0] == frame

    def record(self):
        return json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())

    def type(self, text):
        """The owner enters `text` in the seat's agy: the conversation it went to, once heard."""
        before = self.heard.read_text().count("\n") if self.heard.exists() else 0
        for keys in (("-l", text), ("Enter",)):
            self.assertEqual(self.home.tmux("send-keys", "-t", "=acme:", *keys).code, 0)
        until = time.monotonic() + 120
        while True:
            lines = self.heard.read_text().splitlines()[before:] if self.heard.exists() else []
            found = next((json.loads(line)[1] for line in lines if json.loads(line)[0] == text),
                         None)
            if found:
                return found
            self.assertLess(time.monotonic(), until, "the seat's agy never heard it")
            time.sleep(0.05)

    def test_the_owner_s_words_before_the_clear_owe_a_check_that_finds_the_gap(self):
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], "acme  done")
        checked = self.fake.dir / "checked.md"
        self.fake.behave({"sh": f"cp conversation.md {shlex.quote(str(checked))}; "
                                f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- "
                                f"{shlex.quote(SECOND)} . | head -n 1):1\" 'no receipt email' "
                                f"'the owner asked for it' --quote {shlex.quote(SECOND)}",
                          "final": "Checked.", "hand_in": [["done"]]})
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        read = checked.read_text()
        self.assertEqual([read.count(said) for said in (FIRST, SECOND, " thanks\n")], [1, 1, 1],
                         read)

    def test_reopening_the_seat_once_agy_is_gone_resumes_the_conversation_it_went_to(self):
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        done = self.home.ak("orch", "acme", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        calls = [json.loads(line) for line in self.adapter_log.read_text().splitlines()]
        # the conversation to open and no `new`: one to resume (`interactive <model> <effort>
        # [id [new]]`)
        self.assertEqual([call for call in calls if call[0] == "interactive"][-1][3:], [self.b])

    def test_a_prompt_in_one_with_no_database_or_another_seat_s_leaves_the_seat_where_it_was(self):
        for conversation in (GHOST, OWN, LEFT):
            with self.subTest(conversation=conversation):
                self.showing.write_text(conversation)
                self.assertEqual(self.type(f"hello {conversation}"), conversation)
                record = self.record()
                self.assertEqual(record["conversation"], self.b)
                self.assertEqual([was["conversation"] for was in record["left"]], [self.a])


if __name__ == "__main__":
    unittest.main()
