"""A card question and its answer name the seat's conversation, as its done would.

Black-box: AK_BIN runs before an akseat whose Claude Code hooks fire through hookdrive.
The owner rows keep the harness and conversation, never the seat's reusable name.
"""

from contextlib import closing
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures import hookdrive
from test_key_card_question_is_owner_time import LAYOUT, card


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OwnerRowConversation(unittest.TestCase):
    def test_a_card_question_and_its_answer_name_the_conversation_that_asked(self):
        with Home() as home:
            seat = Seat(home, "acme", screen="claude-working-pane.txt")
            hooks = hookdrive.Hooks(home)
            fired = hooks.prompt("go", seat)
            self.assertEqual(fired.code, 0, fired.err)
            for event, answered in (("PreToolUse", False), ("PostToolUse", True)):
                fired = hooks.fire(event, card(LAYOUT, answered=answered), seat=seat.name,
                                   pane=seat, finished=True)
                self.assertEqual(fired.code, 0, fired.err)
            with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(owner)")}
                self.assertIn("conversation", columns)
                rows = db.execute("SELECT kind, conversation FROM owner ORDER BY at").fetchall()
            conversation = f"claude:{seat.record['conversation']}"
            self.assertEqual(rows, [("asked", conversation), ("answered", conversation)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
