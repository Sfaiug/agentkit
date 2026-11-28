"""An agy seat's model calls are kept.

agy keeps each conversation as a SQLite store, one row per step, each blob a protocol buffer.  A
model call leaves a step of `step_type` 15 whose `metadata` 9 is its usage: 9.2 its uncached
input, 9.5 its cached input, 9.3 its output, each left out where 0, 9.11 the response id, 9.1 the
model as a number, which `gen_metadata.data` names at 1.19 beside 1.4.1; a failed call leaves an
empty 9.  Its step's `metadata` 8 is when it finished, 1 when it began.  A tick files each call
of the conversation a seat owns in history.db's `seat_usage`, as `antigravity:<response id>`:
the moment it finished, else began, its input, no cache write, its cached input and output,
their sum, the model named by its number (none where the store names it nowhere), under the
seat's project, login, and the model and effort it orchestrates with.  A store is read whole at
each tick, and a response id is one call wherever it appears: a call already filed changes
nothing, though another step of its id counts more.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, over a seat of tests/fixtures/akseat.py whose store is
written as agy writes one, under invented ids and model names.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

CONVERSATION = "5d2e8f1a-6b4c-4f3e-8a9d-1c7b3e5f9a01"
T0 = 1_795_770_000      # 2026-11-27 09:00 UTC
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


def number(field, value):
    """A varint field, left out where 0 as a protocol buffer leaves it."""
    return varint(field << 3) + varint(value) if value else b""


def nested(field, data):
    return varint(field << 3 | 2) + varint(len(data)) + data


def stamp(field, at):
    seconds, fraction = divmod(at, 1)
    return nested(field, number(1, int(seconds)) + number(2, round(fraction * 1e9)))


def call(response, model, fresh, cached, output, began, finished=None):
    """A model call's step metadata: its usage (9) and when it began (1) and finished (8)."""
    usage = (number(1, model) + number(2, fresh) + number(3, output) + number(5, cached)
             + nested(11, response.encode()))
    return stamp(1, T0 + began) + (stamp(8, T0 + finished) if finished else b"") + nested(9, usage)


def write(path, *steps):
    """Those step metadata into that store, after the steps it holds, each a model call's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'steps'").fetchone():
            for table in TABLES:
                db.execute(table)
            # the one generation naming a model: number 7 is argon-2
            db.execute("INSERT INTO gen_metadata VALUES (0, ?)",
                       (nested(1, nested(4, number(1, 7)) + nested(19, b"argon-2")),))
        start, = db.execute("SELECT count(*) FROM steps").fetchone()
        db.executemany("INSERT INTO steps VALUES (?, 15, ?, X'')",
                       enumerate(steps, start))


def tick(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err


def filed(home):
    """Every usage row, as (event, project, seconds past T0, tokens, login, model, input, cache
    write, cache read, output, orchestrator, effort)."""
    with closing(sqlite3.connect((home.path / ".agentkit/history.db").as_uri() + "?mode=ro",
                                 uri=True)) as db:
        return [(event, repo, round(at - T0, 3), *kept) for event, repo, at, *kept in db.execute(
            "SELECT event, repo, at, tokens, account, model, input, cache_write, cache_read, "
            "output, orchestrator, effort FROM seat_usage ORDER BY at")]


# acme's three calls, as it orchestrates with gemini at its own effort on its own login: the
# second's model is a number the store names nowhere, and its step has not finished.
CALLS = [
    ("antigravity:resp-acme-1", "acme", 18.5, 6540, "second", "argon-2", 1200, 0, 5000, 340,
     "gemini", "low"),
    ("antigravity:resp-acme-2", "acme", 40.0, 860, "second", None, 800, 0, 0, 60,
     "gemini", "low"),
    ("antigravity:resp-acme-3", "acme", 95.25, 7020, "second", "argon-2", 0, 0, 6900, 120,
     "gemini", "low"),
]


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AnAgySeatsUsageIsKept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["gemini"])  # no audit, which opens a seat of its own
        Seat(home, "acme", model="gemini", composer=">", screen="antigravity-prompt-pane.txt",
             record={"conversation": CONVERSATION, "repo": str(home.path / "code/acme"),
                     "account": "second", "home_account": "second",
                     "efforts": {"gemini": {"effort": "low"}}})
        store = home.path / ".gemini/antigravity-cli/conversations" / f"{CONVERSATION}.db"
        write(store, call("resp-acme-1", 7, 1200, 5000, 340, 10, 18.5),
              # a failed call: an empty usage
              stamp(1, T0 + 20) + stamp(8, T0 + 31) + nested(9, b""),
              call("resp-acme-2", 9, 800, 0, 60, 40))
        cls.seen = []
        for _ in range(2):
            tick(home)
            cls.seen.append(filed(home))
        write(store, call("resp-acme-3", 7, 0, 6900, 120, 90, 95.25),
              call("resp-acme-1", 7, 1800, 5000, 340, 10, 18.5))     # the first's id again
        tick(home)
        cls.seen.append(filed(home))

    def test_each_model_call_is_filed_with_its_counts_model_and_moment(self):
        self.assertEqual(self.seen[0], CALLS[:2])

    def test_a_store_read_again_files_each_call_once(self):
        self.assertEqual(self.seen[1:], [CALLS[:2], CALLS])


if __name__ == "__main__":
    unittest.main()
