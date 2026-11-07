"""`ak run gc` never ends a conversation a seat's record holds, its current one or one it left.

One seat of each harness whose conversations gc ends -- Codex, OpenCode, Antigravity, Muse and
Grok Build -- holds conversations as old as one of that harness no seat holds: forty days.  gc
ends only those no seat holds, as its dry run says it will, and a seat's once its record is gone.
A harness one of whose seats cannot say which conversation it holds keeps all of its own, and the
seat what it left; a record gc cannot read whole -- no JSON, none of a record's, a rename that
names no seat, a harness that is no name -- keeps every conversation; and one a seat takes
while gc runs stays.

Each store is laid out as tests/test_gc_*_conversations.py and tests/test_gc_harness_transcripts.py
lay them out, and the fake `codex`, `opencode` and `grok` end one the way the real ones do.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, boxed
with a /tmp and processes of its own.
"""

import contextlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, boxable, Home
from fixtures.garbage import DAY, ROOM

AGE = 40 * DAY
BOX = ("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--unshare-pid", "--proc", "/proc")
THREAD = "01a06837-7de8-7f32-a435-95eeece164e{}"
CODEX, OPENCODE, MUSE, LATE = "a" * 32, "b" * 32, "c" * 32, "d" * 32   # seats' launch tokens
PYTHON = shlex.quote(sys.executable)
DELETE = """import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("DELETE FROM session_v2 WHERE ? IN (id, parent_id)", (sys.argv[2],))
db.commit()
"""
# as the first of two OpenCode sessions goes, a seat is launched on the other
TAKE = """import json, pathlib, sys
receipt, gone = pathlib.Path(sys.argv[1]), sys.argv[2]
if not receipt.exists():
    receipt.mkdir()
    (receipt / "session").write_text("ses_late" if gone == "ses_free" else "ses_free")
    (receipt.parent / "session-acme-late.json").write_text(json.dumps(
        {"orchestrator": "mimo", "opencode_launch": receipt.name.rpartition("-")[2]}))
"""


def sql(path, *statements):
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        return [row for statement in statements for row in db.execute(*statement)]


@unittest.skipUnless(boxable(), "no bwrap able to box a collection here")
class SeatConversations(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        cwd = str(home.path / "code/acme")
        state = ".agentkit/state"
        # Codex: the seat's thread, the one it left and one nobody holds, read by their headers
        self.threads = [home.write(
            f".codex/sessions/2026/09/28/rollout-2026-09-28T10-00-0{n}-{THREAD.format(n)}.jsonl",
            json.dumps({"type": "session_meta", "payload": {"id": THREAD.format(n), "cwd": cwd}})
            + "\n", ago=AGE) for n in (1, 2, 3)]
        home.write(f"{state}/session-acme-astra.json", {
            "orchestrator": "astra", "cwd": cwd, "codex_launch": CODEX,
            "left": [{"harness": "codex", "conversation": THREAD.format(2), "cwd": cwd}]})
        home.write(f"{state}/codex-launch-{CODEX}.json", {"launch": CODEX, "cwd": cwd, "event": {
            "hook_event_name": "SessionStart", "source": "startup", "cwd": cwd,
            "session_id": THREAD.format(1), "transcript_path": str(self.threads[0])}})
        home.fake("codex", '#!/bin/sh\nfor id; do :; done\n'
                           'find "$CODEX_HOME/sessions" -name "rollout-*-$id.jsonl" -delete\n')
        # OpenCode: rows of its database, the seat's named by its launch's receipt
        self.db = home.path / ".local/share/opencode/opencode.db"
        self.db.parent.mkdir(parents=True)
        self.updated = updated = int((time.time() - AGE) * 1000)
        sql(self.db, ("CREATE TABLE session_v2 (id TEXT PRIMARY KEY, parent_id TEXT,"
                      " time_updated INTEGER NOT NULL)",),
            ("INSERT INTO session_v2 VALUES ('ses_held', NULL, ?), ('ses_free', NULL, ?)",
             (updated, updated)))
        home.write(f"{state}/session-acme-mimo.json", {"orchestrator": "mimo",
                                                       "opencode_launch": OPENCODE})
        home.write(f"{state}/opencode-launch-{OPENCODE}/session", "ses_held")
        delete = home.write("opencode-delete.py", DELETE)
        self.delete = f'exec {PYTHON} {delete} {self.db} "$4"\n'
        home.fake("opencode", "#!/bin/sh\n" + self.delete)
        # Antigravity: a database per conversation, the seat's the one its launcher issued
        self.agy = [home.write(f".gemini/antigravity-cli/conversations/agy-{kind}.db", "steps",
                               ago=AGE) for kind in ("held", "free")]
        home.write(f"{state}/session-acme-gemini.json", {
            "orchestrator": "gemini", "id_source": "launcher", "conversation": "agy-held"})
        # Muse: a folder per session and a row of its index, the seat's named by its receipt
        index = home.path / ".local/share/muse/session-index.db"
        self.muse = [home.write(f".local/share/muse/sessions/2026/09/28/muse-{kind}/session.jsonl",
                                "{}\n", ago=AGE).parent for kind in ("held", "free")]
        sql(index, ("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, session_dir TEXT,"
                    " session_log_path TEXT UNIQUE)",),
            *(("INSERT INTO sessions VALUES (?, ?, ?)",
               (folder.name, str(folder), str(folder / "session.jsonl"))) for folder in self.muse))
        home.write(f"{state}/session-acme-spark.json", {"orchestrator": "spark",
                                                        "muse_launch": MUSE})
        home.write(f"{state}/muse-launch-{MUSE}/session", "muse-held")
        # Grok Build: a folder per session under its cwd, the seat's the one it was launched on
        self.grok = [home.write(f".grok/sessions/%2Fcode%2Facme/grok-{kind}/summary.json", "{}\n",
                                ago=AGE).parent for kind in ("held", "free")]
        home.write(f"{state}/session-acme-grok.json", {"orchestrator": "grok",
                                                       "conversation": "grok-held"})
        home.fake("grok", '#!/bin/sh\nrm -r "$GROK_HOME"/sessions/*/"$3"\n')

    def gc(self, *args):
        done = self.home.run(*self.home.box(BOX), AK, "run", "gc", *args, env=ROOM)
        self.assertEqual((done.code, done.err), (0, ""))
        return done.out

    def sessions(self):
        return {row[0] for row in sql(self.db, ("SELECT id FROM session_v2",))}

    def test_gc_ends_only_what_no_seat_holds_and_a_seats_once_its_record_is_gone(self):
        planned = {line.split()[4].removesuffix(":") for line in self.gc("--dry-run").splitlines()
                   if line.startswith("gc: would remove conversation ")}
        free = {str(self.threads[2]), "ses_free", str(self.agy[1]), str(self.muse[1]),
                str(self.grok[1])}
        self.assertEqual(planned, free)
        self.gc()
        held = [*self.threads[:2], self.agy[0], self.muse[0], self.grok[0]]
        self.assertEqual([path for path in held if not path.exists()], [])
        self.assertEqual([path for path in free - {"ses_free"} if os.path.lexists(path)], [])
        self.assertEqual(self.sessions(), {"ses_held"})
        (self.home.path / ".agentkit/state/session-acme-astra.json").unlink()
        self.gc()
        self.assertFalse(self.threads[0].exists() or self.threads[1].exists())
        self.assertTrue(all(path.exists() for path in held[2:]))
        self.assertEqual(self.sessions(), {"ses_held"})

    def test_a_seat_whose_conversation_cannot_be_read_keeps_its_harness_and_what_it_left(self):
        # an OpenCode seat whose launch's receipt holds no text, which left Antigravity's
        self.home.write(".agentkit/state/session-acme-late.json", {
            "orchestrator": "mimo", "opencode_launch": LATE,
            "left": [{"harness": "antigravity", "conversation": "agy-free"}]})
        self.home.write(f".agentkit/state/opencode-launch-{LATE}/session", "").write_bytes(b"\xff")
        self.gc()
        self.assertEqual(self.sessions(), {"ses_held", "ses_free"})
        self.assertTrue(self.agy[1].exists())
        self.assertFalse(self.threads[2].exists())

    def test_a_record_gc_cannot_read_whole_keeps_every_conversation(self):
        record = self.home.path / ".agentkit/state/session-acme-late.json"
        seat = {"orchestrator": "grok", "conversation": "grok-late"}
        for written in ("{", "null", {**seat, "renamed": None},
                        {**seat, "left": [{"harness": 0, "conversation": "agy-free"}]}):
            with self.subTest(written):
                record.write_text(written if isinstance(written, str) else json.dumps(written))
                self.gc()
                self.assertEqual(self.sessions(), {"ses_held", "ses_free"})
                self.assertEqual([path for path in (self.threads[2], self.agy[1], self.muse[1],
                                                    self.grok[1]) if not path.exists()], [])

    def test_a_conversation_a_seat_takes_while_gc_runs_stays(self):
        sql(self.db, ("INSERT INTO session_v2 VALUES ('ses_late', NULL, ?)", (self.updated,)))
        receipt = self.home.path / f".agentkit/state/opencode-launch-{LATE}"
        take = self.home.write("opencode-take.py", TAKE)
        self.home.fake("opencode", f'#!/bin/sh\n{PYTHON} {take} {receipt} "$4"\n{self.delete}')
        self.gc()
        self.assertEqual(self.sessions(), {"ses_held", (receipt / "session").read_text()})


if __name__ == "__main__":
    unittest.main()
