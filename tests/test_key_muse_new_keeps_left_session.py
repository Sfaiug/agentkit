"""A Muse seat follows the session its own Muse last completed a turn in, and keeps each one it
left, or one a turn was interrupted in, for its done check and cleanup.  Its launch reports
session A, where the owner asks for a retry button and a receipt email; `/new` opens B, firing no
hook, where they say only "thanks"; each turn's Stop names its session.  The plan holds the
button alone, every line done.  The seat does not read done, `ak orch check` quotes the email
from a workspace holding A and B once each, and a reopen resumes B.  A turn in A again leaves the
check reading each once; an Esc's Interrupt in a third session, where the owner asked for more,
puts that ask in the check too and moves the seat nowhere; a Stop naming another session from a
process that is not the seat's Muse leaves the seat where it was; and `ak run gc` ends neither A
nor B once nobody wrote to them for 40 days, though it ends a session no seat holds.  Black-box
on `AK_BIN`, a fake model (fakeadapter.py), and a seat opened by `ak orch` from a person's
terminal on a fake muse that fires each hook its line carries as Muse 1.4.12 does, its sessions
logged in Muse's store under the Home (tests/fixtures/musetui.py).
"""

import contextlib
import json
import os
import shlex
import sqlite3
import sys
import time
import types
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, musetui
from fixtures.akbin import AK, REAL_TMUX, REPO, Home, boxable
from fixtures.akterm import Terminal
from fixtures.garbage import DAY, ROOM
from fixtures.hookdrive import adapter

FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
MORE = "And show the upload's progress."
STORE = ".local/share/muse/sessions/2026/11/08"
BOX = ("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--unshare-pid", "--proc", "/proc")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseNewKeepsLeftSession(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        musetui.install(home)
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        adapters = Path(home.env["AGENTKIT_ADAPTER_DIR"])     # Muse's own beside the fake
        (adapters / "muse.sh").write_text(
            f'#!/bin/sh\nexec {shlex.quote(str(REPO / "adapters/muse.sh"))} "$@"\n')
        (adapters / "muse.sh").chmod(0o755)
        akconfig.write(home, ["spark", "opus"], workers=["spark"],
                       extra='[done_check]\nmodel = "opus"')
        home.write(".agentkit/state/plan-acme.md", "- [x] The upload page has a retry button · "
                   "check: `true` · acme · written 2026-11-08 10:05 · done 0123456789ab\n")
        self.checked = self.fake.dir / "checked.md"
        self.fake.behave({"sh": f"cp conversation.md {shlex.quote(str(self.checked))}; "
                                f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- "
                                f"{shlex.quote(SECOND)} . | head -n 1):1\" 'no receipt email' "
                                f"'the owner asked for it' --quote {shlex.quote(SECOND)}",
                          "final": "Checked.", "hand_in": [["done"]]})
        self.a = self.open("--model", "spark", "--workers", "spark")["session"]
        self.turn(self.a, FIRST, SECOND)
        self.b = str(uuid.uuid4())      # `/new`, which fires no hook
        self.turn(self.b, "thanks")
        self.assertEqual(self.record()["conversation"], self.b, "the seat stayed on A")

    def open(self, *args):
        """`ak orch acme` from a person's terminal: what its Muse said it opened, once it has."""
        term = Terminal(self.home, "orch", "acme", *args, size=(120, 40))
        try:
            return musetui.started(self.home, "acme")
        except AssertionError:
            raise AssertionError(f"no muse started; the terminal shows:\n{term.screen()}") from None

    def turn(self, session, *asks, ended="Stop"):
        """The owner asks `asks` in that session, logged with Muse's answers in its store, and the
        seat's Muse ends the turn there: its Stop names the session, or an Esc's Interrupt."""
        log = self.home.path / STORE / session / "session.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            for ask in asks:
                run = uuid.uuid4().hex
                for event in ({"kind": "started", "prompt": ask},
                              {"kind": "assistant_message_committed", "text": "Done."}):
                    fh.write(json.dumps({
                        "schema_version": 1, "stream": {"kind": "session", "id": session},
                        "record_type": "event", "recorded_at": round(time.time() * 1e6),
                        "payload": {"kind": "run", "run_id": run, "event": event}}) + "\n")
        musetui.stop(self.home, "acme", session, ended)

    def record(self):
        return json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())

    def reopened_on(self):
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        argv = self.open()["argv"]
        return argv[argv.index("resume") + 1]

    def check(self, *asks):
        """The seat not done, its check quoting the email from a workspace holding each of
        `asks` once."""
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], "acme  done")
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        read = self.checked.read_text()
        self.assertEqual([read.count(ask) for ask in asks], [1] * len(asks), read)

    def test_the_owner_s_words_in_the_session_left_owe_a_check_that_finds_the_gap(self):
        self.check(SECOND, " thanks\n")

    def test_reopening_the_seat_resumes_the_session_it_went_to(self):
        self.assertEqual(self.reopened_on(), self.b)

    def test_a_turn_back_in_the_session_left_reads_each_once(self):
        self.turn(self.a, "Go on.")
        self.assertEqual(self.record()["conversation"], self.a)
        self.check(SECOND, " thanks\n")

    def test_an_interrupted_session_s_ask_is_checked_and_the_seat_reopens_on_its_last_stop_s(self):
        self.turn(str(uuid.uuid4()), MORE, ended="Interrupt")
        self.check(SECOND, " thanks\n", MORE)
        self.assertEqual(self.reopened_on(), self.b)

    def test_a_stop_from_a_process_not_the_seat_s_muse_leaves_the_seat_where_it_was(self):
        other = str(uuid.uuid4())
        self.home.write(f"{STORE}/{other}/session.jsonl", "{}\n")
        # from the seat's pane, as its Muse's hooks are, but fired by the test
        pane = self.home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_id}").out.strip()
        fired = adapter(self.home, "muse", "hook", payload={
            **musetui.ENDED["Stop"], "session_id": other, "cwd": self.record()["cwd"]},
            seat="acme", pane=types.SimpleNamespace(pane=pane))
        self.assertEqual(fired.code, 0, fired.err)
        self.assertEqual(self.record()["conversation"], self.b)

    @unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
    def test_gc_ends_neither_session_the_seat_ran_a_turn_in(self):
        free = self.home.write(f"{STORE}/{uuid.uuid4()}/session.jsonl", "{}\n").parent
        folders = [self.home.path / STORE / self.a, self.home.path / STORE / self.b, free]
        index = self.home.path / ".local/share/muse/session-index.db"
        with contextlib.closing(sqlite3.connect(index)) as db, db:
            db.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, session_dir TEXT,"
                       " session_log_path TEXT UNIQUE)")
            db.executemany("INSERT INTO sessions VALUES (?, ?, ?)", [
                (folder.name, str(folder), str(folder / "session.jsonl")) for folder in folders])
        then = time.time() - 40 * DAY
        for folder in folders:
            os.utime(folder / "session.jsonl", (then, then))
        # boxed apart from every process: no file one holds open keeps a session, only the seat
        done = self.home.run(*self.home.box(BOX), AK, "run", "gc", env=ROOM)
        self.assertEqual((done.code, done.err), (0, ""))
        self.assertEqual([folder.exists() for folder in folders], [True, True, False])
        self.check(SECOND)


if __name__ == "__main__":
    unittest.main()
