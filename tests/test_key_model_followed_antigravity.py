"""A model or effort switched inside an Antigravity seat, not through ak, becomes that seat's own:
once ak has looked at the seat, its row in the popup names the model its latest answer done since
the launch ran on, one begun before it too, and its `c` puts the orchestrator mark there, at that
answer's effort; an answer done before the launch moves nothing, though its turn ends after it,
nor does a newest generation that failed (the owner, 30 Oct 2026).  Black-box: `AK_BIN orch list`
looks at akseat.py seats whose conversations are written where and the way agy 1.4.11 writes
them, then `AK_BIN` is the moved seat's popup; it fails against `/bin/false`."""

import contextlib
import json
import re
import sqlite3
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

FLASH, ARGON = "gemini-3.8-flash-high", "gemini-4-argon-low"
# agy's two tables, as far as the columns read go
TABLES = ("CREATE TABLE `steps` (`idx` integer,`step_type` integer NOT NULL DEFAULT 0,"
          "`metadata` blob,`step_payload` blob,PRIMARY KEY (`idx`))",
          "CREATE TABLE `gen_metadata` (`idx` integer,`data` blob,PRIMARY KEY (`idx`))")


def varint(value):
    out = b""
    while True:
        byte, value = value & 0x7F, value >> 7
        if not value:
            return out + bytes([byte])
        out += bytes([byte | 0x80])


def nested(field, data):
    return varint(field << 3 | 2) + varint(len(data)) + data


def stamp(field, at):
    seconds, fraction = divmod(at, 1)
    return nested(field, varint(1 << 3) + varint(int(seconds)) + varint(2 << 3)
                  + varint(round(fraction * 1e9)))


def agy(home, seat, answers, failed=None):
    """That seat's conversation in agy's store, each answer (the model it ran on by agy's id, the
    moment it was done) an execution of its own: a user input, the answer, made a minute before,
    and its generation, which names the model only while it is the newest; then, `failed`, a
    generation on that model that made no answer."""
    path = home.path / ".gemini/antigravity-cli/conversations" / f"{seat.record['conversation']}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    generations = [*answers, (failed, None)] if failed else answers
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        for table in TABLES:
            db.execute(table)
        for n, (model, at) in enumerate(generations):
            run = f"run-{n}".encode()
            if at is not None:
                made = stamp(1, at - 60)
                for kind, metadata in ((14, made), (15, made + stamp(8, at))):
                    db.execute("INSERT INTO steps (idx, step_type, metadata) VALUES (?, ?, ?)",
                               (2 * n + kind - 14, kind, metadata + nested(12, run)))
            named = nested(28, model.encode()) if n == len(generations) - 1 else b""
            db.execute("INSERT INTO gen_metadata (idx, data) VALUES (?, ?)",
                       (n, nested(3, named) + nested(4, run)))


def marked(screen):
    """The model `c` marks as the seat's orchestrator, and the effort after that mark's bar; the
    row under the cursor brackets its mark."""
    found = re.search(r"^[› ] (.+?) +\[?●\]? +\S+ +(\S+)", screen, re.M)
    return found and found.groups()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelFollowedInsideAntigravity(unittest.TestCase):
    def test_an_answer_done_since_the_launch_moves_the_seat(self):
        """Seats on gemini launched 600 seconds ago: one whose latest answer, on Argon at `low`,
        began before that and was done since shows as on argon; one whose same answer was done
        40 seconds before its launch, and one whose newest generation, on Argon, failed after an
        answer on its own model, stay as they were."""
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"gemini": {}, "argon": {"harness": "antigravity",
                                                       "model": "gemini-4-argon"}})
        fakeadapter.install(home, antigravity="pass")
        now = time.time()
        for name, answers, failed in (
                ("acme-new", [(FLASH, now - 1200), (ARGON, now - 560)], None),
                ("acme-old", [(FLASH, now - 1280), (ARGON, now - 640)], None),
                ("acme-failed", [(FLASH, now - 560)], ARGON)):
            seat = Seat(home, name, model="gemini", screen="antigravity-prompt-pane.txt",
                        record={"launched": now - 600})
            agy(home, seat, answers, failed)
        done = home.ak("orch", "list")
        self.assertEqual(done.code, 0, done.out + done.err)
        orchestrators = {name: json.loads((home.path / f".agentkit/state/session-{name}.json")
                                          .read_text())["orchestrator"]
                         for name in ("acme-new", "acme-old", "acme-failed")}
        self.assertEqual(orchestrators, {"acme-new": "argon", "acme-old": "gemini",
                                         "acme-failed": "gemini"})
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-new"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait(lambda screen: any("acme-new" in line and "Gemini 4 Argon" in line
                                     for line in screen.split("\n")))
        term.keys("c")
        term.wait(lambda screen: "esc back" in screen
                  and marked(screen) == ("Gemini 4 Argon", "low"))


if __name__ == "__main__":
    unittest.main()
