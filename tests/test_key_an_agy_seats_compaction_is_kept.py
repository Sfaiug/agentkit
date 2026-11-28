"""An agy seat's compactions are kept.

When agy compacts a conversation it calls the model once more, and keeps that call in a step of
`step_type` 23 rather than as a model step (15).  Its `metadata` 9 is its usage, laid out as a
model step's (tests/test_key_an_agy_seats_usage_is_kept.py), and so is its 28 -> 2 less the
model's number (9.1); an older store keeps only the 28 -> 2.  Its moment is `metadata` 8, else 1,
as a model step's.  A tick files a compaction as it files a model call, in history.db's
`seat_usage` as `antigravity:<response id>`, once: its counts from 9 where 9 holds any, else
from 28 -> 2, and its model by the name the store gives the number 9 holds, else none.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, over seats of tests/fixtures/akseat.py whose stores are
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
from test_key_an_agy_seats_usage_is_kept import T0, TABLES, filed, nested, number, stamp, tick

# acme's store names model 7 argon-2; fix-api's is older, keeping no `gen_metadata` table
STORES = {"acme": ("9b3c1d7e-2f4a-4c8b-9e6d-3a5f7c1b8d02", TABLES),
          "fix-api": ("e4a8c2f6-1b3d-4e7a-8c9f-6d2b4a8e1c03", TABLES[:1])}


def usage(response, fresh, cached, output, model=0):
    return (number(1, model) + number(2, fresh) + number(3, output) + number(5, cached)
            + nested(11, response.encode()))


# acme's first compaction keeps its usage at 9 and at 28 -> 2, as agy writes one today; its
# second a 9 of only its id and model, its counts at 28 -> 2; fix-api's only at 28 -> 2
COMPACTIONS = {
    "acme": [stamp(1, T0 + 10) + stamp(8, T0 + 42.5)
             + nested(9, usage("resp-acme-c", 3300, 511000, 6100, model=7))
             + nested(28, nested(2, usage("resp-acme-c", 3300, 511000, 6100))),
             stamp(1, T0 + 50) + stamp(8, T0 + 58)
             + nested(9, usage("resp-acme-d", 0, 0, 0, model=7))
             + nested(28, nested(2, usage("resp-acme-d", 1500, 509000, 2500)))],
    "fix-api": [stamp(1, T0 + 60) + stamp(8, T0 + 75.25)
                + nested(28, nested(2, usage("resp-fix-c", 2300, 498000, 4000)))],
}
FILED = {
    "acme": [("antigravity:resp-acme-c", "acme", 42.5, 520400, "second", "argon-2", 3300, 0,
              511000, 6100, "gemini", "low"),
             ("antigravity:resp-acme-d", "acme", 58.0, 513000, "second", "argon-2", 1500, 0,
              509000, 2500, "gemini", "low")],
    "fix-api": [("antigravity:resp-fix-c", "fix-api", 75.25, 504300, "second", None, 2300, 0,
                 498000, 4000, "gemini", "low")],
}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AnAgySeatsCompactionIsKept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["gemini"])  # no audit, which opens a seat of its own
        for name, (conversation, tables) in STORES.items():
            Seat(home, name, model="gemini", composer=">", screen="antigravity-prompt-pane.txt",
                 record={"conversation": conversation, "repo": str(home.path / "code" / name),
                         "account": "second", "home_account": "second",
                         "efforts": {"gemini": {"effort": "low"}}})
            store = home.path / ".gemini/antigravity-cli/conversations" / f"{conversation}.db"
            store.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(store)) as db, db:
                for table in tables:
                    db.execute(table)
                if len(tables) > 1:
                    db.execute("INSERT INTO gen_metadata VALUES (0, ?)",
                               (nested(1, nested(4, number(1, 7)) + nested(19, b"argon-2")),))
                db.executemany("INSERT INTO steps VALUES (?, 23, ?, X'')",
                               enumerate(COMPACTIONS[name]))
        cls.seen = []
        for _ in range(2):
            tick(home)
            cls.seen.append(filed(home))

    def kept(self, project):
        return [[row for row in seen if row[1] == project] for seen in self.seen]

    def test_a_compaction_is_filed_once_with_its_counts_and_model(self):
        self.assertEqual(self.kept("acme"), [FILED["acme"]] * 2)

    def test_an_older_stores_compaction_is_filed_with_its_counts_and_no_model(self):
        self.assertEqual(self.kept("fix-api")[0], FILED["fix-api"])


if __name__ == "__main__":
    unittest.main()
