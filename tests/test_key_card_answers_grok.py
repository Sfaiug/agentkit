"""`ak orch check SEAT` gives its model each question the owner answered on a Grok Build seat's
`ask_user_question` card, beside the choices the seat offered and the answer as the owner gave it:
the label picked, the labels ticked joined by ", ", the words typed, or the labels ticked and then
the words typed on a line of their own.  A gap may quote the answer, never a question no answer
came to.

The seat asked three cards: three questions answered with a pick, a typed answer and two ticks;
three of which the owner picked the first, left the second and ticked one of the third with words
typed beside it; and one they dismissed.  Grok keeps the answers only in the card's result, a
message nothing in which is escaped: one typed answer holds the next question's opening with an
answer it did not offer, another holds `, "` and `"=`, and a label picked holds ` user notes: `.
The model's turn hands in its gaps only where its workspace holds the five answered questions,
their choices and their answers, and none of the others: one quoting each typed answer, kept, and
one quoting the dismissed card's question, dropped.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, on a seat of tests/fixtures/akseat.py whose
session's updates.jsonl holds each card as Grok Build 1.0.46 left one answered by keyboard on
7 Nov 2026, with a fake harness of fakeadapter.py for the model.
"""

import json
import shlex
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

CONVERSATION = "0b8f6c2e-4d1a-4e7b-9c3f-5e2a7d1c9b40"
AT = 1_794_045_600     # 7 Nov 2026 10:00 UTC, as Grok stamps an update: in seconds
FONT = 'Sans, "Which pages should show the acme banner?"="every page"'
WIDE = 'Wide" user notes: full bleed'
LINKS = 'Careers, "Jobs"="Careers" in the menu'


def question(text, *labels, multi=False):
    return {"question": text, "options": [{"label": label, "description": f"{label} for acme"}
                                          for label in labels],
            **({"multi_select": True} if multi else {})}


ANSWERED = [   # (question, what its result quotes, the words typed, what the check reads)
    (question("Which colour should the acme banner be?", "Red", "Blue"), "Blue", None, "Blue"),
    (question("Which font should the acme banner use?", "Serif", "Mono"), "Other", FONT, FONT),
    (question("Which pages should show the acme banner?", "Home", "Docs", "Blog", multi=True),
     "Home, Docs", None, "Home, Docs"),
    (question("Which layout should the acme banner use?", "Narrow", WIDE), WIDE, None, WIDE),
    (question("Which links should the acme banner hold?", "Home", "Docs", multi=True),
     "Home", LINKS, f"Home\n{LINKS}")]
UNANSWERED = question("Which icon should the acme banner show?", "Star", "Flag")
DISMISSED = question("Should the acme banner have a close button?", "Yes", "No")
DECLINED = ("User declined to answer the questions. Continue with the task using your best "
            "judgment, or ask different questions.")


def answered(given):
    """An answered card's message: each question answered, in the order asked, unescaped."""
    return ("User has answered your questions: " + ", ".join(
        f'"{asked["question"]}"="{chose}"' + (f" user notes: {typed}" if typed else "")
        for asked, chose, typed, _ in given)
        + ". You can now continue with the user's answers in mind.")


def card(n, questions, message):
    """A card's `session/update` lines: asked, then submitted a minute later."""
    def update(at, **fields):
        return {"jsonrpc": "2.0", "method": "session/update", "timestamp": at, "params": {
            "sessionId": CONVERSATION, "update": {"toolCallId": f"call-acme{n}", **fields}}}
    at = AT + n * 120
    return [update(at, sessionUpdate="tool_call", title="ask_user_question", kind="other",
                   status="pending", rawInput={"questions": questions},
                   _meta={"x.ai/tool": {"name": "ask_user_question"}}),
            update(at + 60, sessionUpdate="tool_call_update", status="completed",
                   rawOutput={"type": "AskUserQuestion", "UserAnswered": {"message": message}})]


def seat(home):
    """A Grok Build seat whose session's durable record holds the three cards."""
    cwd = Seat(home, "acme", model="grok", alive=False,
               record={"conversation": CONVERSATION}).cwd
    asked = [given[0] for given in ANSWERED]
    lines = [*card(1, asked[:3], answered(ANSWERED[:3])),
             *card(2, [asked[3], UNANSWERED, asked[4]], answered(ANSWERED[3:])),
             *card(3, [DISMISSED], DECLINED)]
    home.write(f".grok/sessions/{quote(str(cwd), safe='')}/{CONVERSATION}/updates.jsonl",
               "".join(json.dumps(line) + "\n" for line in lines))


class CardAnswersGrok(unittest.TestCase):
    def test_a_grok_seat_s_card_answers_are_the_owner_s_and_its_other_questions_are_not(self):
        with Home() as home:
            fake = fakeadapter.install(home, grokbuild="pass", claude="pass")["claude"]
            seat(home)
            akconfig.write(home, ["grok", "opus"], extra='[done_check]\nmodel = "opus"')
            # no gap at all unless the workspace holds each answered question, its choices and
            # each line of its answer, and none of the questions no answer came to; then the
            # model writes the dismissed card's question down itself, a quote no answer of the
            # owner's holds.  A kept gap quoting the links answer whole proves its two lines.
            held = [text for asked, *_, answer in ANSWERED for text in (
                asked["question"], *answer.split("\n"),
                *(f"- {option['label']}: {option['description']}" for option in asked["options"]))]
            sh = [f"grep -rqF -- {shlex.quote(text)} . || exit 1" for text in held]
            sh += [f"! grep -rqF -- {shlex.quote(asked['question'])} . || exit 1"
                   for asked in (UNANSWERED, DISMISSED)]
            sh += [f"echo {shlex.quote(DISMISSED['question'])} > notes.md"]
            sh += [f"grep -rlF -- {shlex.quote(found)} . | head -n 1 | while read -r file; do "
                   f"{shlex.quote(AK)} hand-in finding \"$file:1\" 'not in the work' "
                   f"'the owner asked for it' --quote {shlex.quote(quote)}; done"
                   for found, quote in ((FONT, FONT), (LINKS, ANSWERED[4][3]),
                                        (DISMISSED["question"], DISMISSED["question"]))]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(f'the owner: "{FONT}"', done.out)
            self.assertIn(f'the owner: "Home\n  {LINKS}"', done.out)
            self.assertNotIn(DISMISSED["question"], done.out + done.err)
            self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
