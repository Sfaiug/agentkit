"""`ak orch check SEAT` gives its model each question the owner answered on an OpenCode seat's
`question` card, beside the choices the seat offered and the answer as the owner gave it: the label
picked, the words typed instead, or the labels ticked, joined by ", ".  A gap may quote the
answer, never a question no answer came to.

The seat asked three cards: three questions answered with a pick, a typed answer and two ticks;
three of which the owner answered only the first; and one they put down with Esc.  The model's
turn hands in its gaps only where its workspace holds the four answered questions, their choices
and their answers, and none of the others: one quoting the typed answer, one quoting the
dismissed card's question.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a seat of tests/fixtures/akseat.py whose session's opencode.db rows
hold each card as one tool part, shaped as OpenCode 2.2.6 left a card answered by keyboard on
7 Nov 2026, with a fake harness of fakeadapter.py for the model.
"""

import json
import shlex
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

TOKEN, SESSION = "a" * 32, "ses_0fa1c2d3e4ffAcmeCards"
AT = 1_794_045_600_000     # 7 Nov 2026 10:00 UTC, as OpenCode stamps it: in milliseconds
TYPED = "Sans, and make the text bold"


def question(text, *labels, multiple=False):
    return {"question": text, "header": text.split()[1].capitalize(),
            "options": [{"label": label, "description": f"{label} for acme"}
                        for label in labels], **({"multiple": True} if multiple else {})}


ANSWERED = [   # (question, what the owner gave, what the check reads)
    (question("Which colour should the settings page use?", "Blue", "Green"), ["Blue"], "Blue"),
    (question("Which font should the settings page use?", "Serif", "Mono"), [TYPED], TYPED),
    (question("Which pages should link to settings?", "Home", "Docs", "Blog", multiple=True),
     ["Home", "Docs"], "Home, Docs"),
    (question("Which layout should the settings page use?", "Compact", "Tabbed"), ["Tabbed"],
     "Tabbed")]
UNANSWERED = [question("Which icon should the settings link show?", "Gear", "Slider"),
              question("How wide should the settings page be?", "Narrow", "Wide")]
DISMISSED = question("Should the settings page have a dark mode?", "Yes", "No")


def card(n, questions, answers=None):
    """A `question` tool part: submitted with `answers`, one list per question, else put down."""
    state = ({"status": "completed", "metadata": {"answers": answers}} if answers is not None
             else {"status": "error", "error": {"type": "aborted",
                                                "message": "The user dismissed this question"}})
    at = AT + n * 60_000
    return {"type": "tool", "id": f"call_acme{n}", "name": "question", "executed": True,
            "state": {**state, "input": {"questions": questions}},
            "time": {"created": at - 30_000, "ran": at - 29_000, "completed": at}}


def seat(home):
    """An OpenCode seat whose session asked the three cards, beside the receipt naming it."""
    Seat(home, "acme", model="mimo", alive=False, record={"opencode_launch": TOKEN})
    home.write(f".agentkit/state/opencode-launch-{TOKEN}/session", SESSION)
    asked = [q for q, _, _ in ANSWERED]
    rows = [("user", {"text": "Build the acme settings page."}),
            *(("assistant", {"content": [{"type": "text", "text": "A few questions first."},
                                         part]}) for part in (
                card(1, asked[:3], [given for _, given, _ in ANSWERED[:3]]),
                card(2, [asked[3], *UNANSWERED], [ANSWERED[3][1], [], []]),
                card(3, [DISMISSED])))]
    db = home.path / ".local/share/opencode/opencode.db"
    db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE `session_message` (`id` text PRIMARY KEY, `session_id` text"
                     " NOT NULL, `type` text NOT NULL, `seq` integer NOT NULL, `time_created`"
                     " integer NOT NULL, `time_updated` integer NOT NULL, `data` text NOT NULL)")
        for seq, (kind, data) in enumerate(rows):
            at = AT - 600_000 + seq * 60_000
            conn.execute("INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (f"msg_0fa1c2d3e4ffAcme{seq}", SESSION, kind, seq, at, at,
                          json.dumps(data)))


class CardAnswersOpencode(unittest.TestCase):
    def test_an_opencode_seat_s_card_answers_are_the_owner_s_and_its_other_questions_are_not(self):
        with Home() as home:
            fake = fakeadapter.install(home, opencode="pass", claude="pass")["claude"]
            seat(home)
            akconfig.write(home, ["mimo", "opus"], extra='[done_check]\nmodel = "opus"')
            # no gap at all unless the workspace holds each answered question, its choices and
            # its answer, and none of the questions no answer came to
            held = [text for asked, _, answer in ANSWERED for text in (
                asked["question"], answer, *(f"- {option['label']}: {option['description']}"
                                             for option in asked["options"]))]
            sh = [f"grep -rqF -- {shlex.quote(text)} . || exit 1" for text in held]
            sh += [f"! grep -rqF -- {shlex.quote(asked['question'])} . || exit 1"
                   for asked in (*UNANSWERED, DISMISSED)]
            sh += [f"file=$(grep -rlF -- {shlex.quote(TYPED)} . | head -n 1)"]
            sh += [f"{shlex.quote(AK)} hand-in finding \"$file:1\" 'not in the work' "
                   f"'the owner asked for it' --quote {shlex.quote(quote)}"
                   for quote in (TYPED, DISMISSED["question"])]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(f'the owner: "{TYPED}"', done.out)
            self.assertNotIn(DISMISSED["question"], done.out + done.err)
            self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
