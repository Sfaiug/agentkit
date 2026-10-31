"""A question a seat asks on its harness's own card is the owner's time once they answer it.

Before Claude Code draws an AskUserQuestion card it runs its PreToolUse hooks, and the card's
answer reaches its PostToolUse hook.  Each question the card asks the owner answers there is a
question `asked` when the card went up and `answered` then, `waited` between, in history.db's
owner table, which the board reads; the same answer heard again adds nothing.  A question the
seat's standing notice asks already was asked when the notice went up, and its answer is the
notice's: the card adds no row of its own.  A card the seat is refused asks nobody.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before
seats of tests/fixtures/akseat.py whose hooks fire as their harness fires them
(tests/fixtures/hookdrive.py), the rows checked against each other, never the clock.
"""

import json
import sqlite3
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures import hookdrive

LAYOUT = "Which layout should acme use?"
NAMING = "Which naming should acme use?"
CHOICES = {LAYOUT: ["Compact (Recommended)", "Wide"], NAMING: ["snake_case (Recommended)", "camelCase"]}
ANSWERS = {LAYOUT: "Compact (Recommended)", NAMING: "snake_case (Recommended)"}
UPDATE = "Run fix-api ended: merged."     # a run update ak types, the owner's words in none


def card(*asked, answered=False):
    """Claude Code 2.1.305's payload for its AskUserQuestion card: going up, or `answered`, the
    owner's answers keyed by each question."""
    questions = [{"question": q, "header": "Pick", "multiSelect": False,
                  "options": [{"label": label, "description": f"{label} for acme."}
                              for label in CHOICES[q]]} for q in asked]
    payload = {"tool_name": "AskUserQuestion", "tool_use_id": "toolu_acme",
               "tool_input": {"questions": questions}}
    if answered:
        payload["tool_response"] = {"questions": questions,
                                    "answers": {q: ANSWERS[q] for q in asked}}
    return payload


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CardQuestionIsOwnerTime(unittest.TestCase):
    def setUp(self):
        # the owner's rows name no seat: each case reads a Home of its own
        self.home = Home()
        self.addCleanup(self.home.close)
        self.hooks = hookdrive.Hooks(self.home)

    def rows(self):
        """The owner table, `{kind: [(at, waited), ...]}`, oldest first."""
        path = self.home.path / ".agentkit" / "history.db"
        if not path.exists():
            return {}
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
            found = db.execute("SELECT at, kind, waited FROM owner ORDER BY at").fetchall()
        rows = {}
        for at, kind, waited in found:
            rows.setdefault(kind, []).append((at, waited))
        return rows

    def paired(self, rows, count):
        """`count` questions asked and answered, each answer dated after its question by its
        wait."""
        self.assertEqual(sorted(rows), ["answered", "asked"], rows)
        self.assertEqual((len(rows["asked"]), len(rows["answered"])), (count, count), rows)
        for asked, since in zip(sorted(at for at, _ in rows["asked"]),
                                sorted(at - waited for at, waited in rows["answered"])):
            self.assertAlmostEqual(asked, since, delta=1e-6)
        for at, waited in rows["answered"]:
            self.assertGreater(waited, 0)

    def asked(self, seat, payload):
        """The card about to go up: what the seat's PreToolUse hooks printed."""
        fired = self.hooks.fire("PreToolUse", payload, seat=seat.name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        return fired.said

    def answer(self, seat, payload):
        """The owner answers the card; its model then goes on, while the hook's work ends."""
        fired = self.hooks.fire("PostToolUse", payload, seat=seat.name, pane=seat, finished=True)
        self.assertEqual(fired.code, 0, fired.err)

    def ak(self, seat, *args):
        """`ak ARGS` run in the seat, its output."""
        done = self.home.ak(*args, env={"AGENTKIT_SESSION": seat.name}, cwd=seat.cwd)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def test_each_question_a_card_asks_is_asked_and_answered_once(self):
        seat = Seat(self.home, "acme", screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        self.assertEqual(self.asked(seat, card(LAYOUT, NAMING)), [])
        self.answer(seat, card(LAYOUT, NAMING, answered=True))
        rows = self.rows()
        self.paired(rows, 2)
        self.answer(seat, card(LAYOUT, NAMING, answered=True))
        self.assertEqual(self.rows(), rows)

    def test_a_card_asking_what_the_notice_asks_adds_no_row_of_its_own(self):
        seat = Seat(self.home, "beta", screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        self.ak(seat, "notify", "needs", LAYOUT)
        seat.show("claude-prompt-pane.txt")
        chat = hookdrive.transcript(self.home, seat.name, LAYOUT)
        fired = self.hooks.fire("Stop", {"background_tasks": [], "stop_hook_active": False,
                                         "transcript_path": chat}, seat=seat.name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        # the look the Stop starts asks it, a moment after
        deadline = time.monotonic() + 10
        while not self.rows() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(sorted(self.rows()), ["asked"])
        # a run update opens the next turn, where the seat asks it again on its card
        self.hooks.fire("UserPromptSubmit", {"prompt": UPDATE}, seat=seat.name, pane=seat)
        seat.show("claude-working-pane.txt")
        self.assertEqual(self.asked(seat, card(LAYOUT)), [])
        self.answer(seat, card(LAYOUT, answered=True))
        self.paired(self.rows(), 1)

    def test_a_refused_card_asks_nobody(self):
        rig = Rig(self.home, "gamma")
        seat = Seat(self.home, "gamma", screen="claude-working-pane.txt", cwd=rig.path,
                    record={"repo": str(rig.path)})
        self.hooks.prompt("go", seat)
        # its plan done, every line ticked, with nothing from the owner since
        self.ak(seat, "plan", "add", "parser.py is on main", "--check", "test -f parser.py")
        rig.commit({"parser.py": "parse = str.split\n"}, "the parser")
        self.ak(seat, "plan")
        said = self.asked(seat, card(LAYOUT))
        self.assertEqual([out["hookSpecificOutput"]["permissionDecision"] for out in said],
                         ["deny"], json.dumps(said))
        self.answer(seat, card(LAYOUT, answered=True))
        self.assertEqual(self.rows(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
