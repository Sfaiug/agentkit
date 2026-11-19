"""A seat's spend at listed prices outlives its model's place on the boards.

A board drops a model once its maker ships the next one.  A seat's `seat_usage` row costs what
its counts cost at the prices the boards stored as a tick read its line listed for its model, a
repeat of the line counting more priced anew, so `ak usage --json` gives its login the same
`listed_usd` once the boards stored later list it no more.  A row of a model those boards listed
nothing for is priced as it is read: it costs what the login's priced rows cost a token
(tests/test_key_listed_spend.py).

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its tick
in the box `home.tick()` builds, on a seat of tests/fixtures/akseat.py whose conversation is
written as Claude Code writes it, of the two models tests/test_key_turn_row_keeps_listed.py's
turn counts, an invented board in its Home before the tick and another after it, and a
history.db from before rows kept dollars, so the tick's write is the one adding them.
"""

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from test_key_listed_spend import SEAT_USAGE
from test_key_seat_tokens_by_type import CONVERSATION, append, said, tick
from test_key_turn_row_keeps_listed import MODELS, SPENT, board


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ASeatOnAModelTheBoardsDrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])     # no audit, which opens a seat of its own
        seat = Seat(home, "acme", record={"conversation": CONVERSATION,
                                          "repo": str(home.path / "code/acme")})
        folder = home.path / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        # a message of each model an hour ago, Claude Code writing a line for each of its
        # blocks, the earlier one counting less of its output
        at = time.time() - 3600
        append(folder / f"{CONVERSATION}.jsonl", *(
            said(f"msg_01{model}", at, *counts[:3], output, model=model)
            for model, counts in MODELS.items() for output in (counts[3] // 4, counts[3])))
        home.write(".agentkit/state/boards.json", board("anvil-1", "Anvil 1"))
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            db.execute(SEAT_USAGE)
        tick(home)
        cls.before = home.ak("usage", "--json")
        # its maker shipped the next one
        home.write(".agentkit/state/boards.json", board("anvil-2", "Anvil 2"))
        cls.after = home.ak("usage", "--json")

    def spent(self, done):
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["providers"]["anthropic"]["listed_usd"]   # its one login

    def test_its_login_spent_at_the_prices_listed_as_its_lines_were_read(self):
        self.assertAlmostEqual(self.spent(self.before), SPENT)

    def test_its_login_spent_the_same_once_the_boards_list_its_model_no_more(self):
        self.assertAlmostEqual(self.spent(self.after), SPENT)


if __name__ == "__main__":
    unittest.main()
