"""A fresh agy 1.5 composer's grey mode hint is an empty composer, never a line typed.

Before a conversation's first prompt agy 1.5 draws a mode hint in grey (`\x1b[90m`) inside its
empty composer, and typed text in the terminal's own colour.  The colour, never the hint's words,
tells them apart: a grey hint reads as empty (`watch.composer_draft` is `""`, and the seat takes
an owed line as any empty composer does), the same words typed in the terminal's own colour read
as a draft, and a plain capture with no colours reads as today.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, REPO, Home, boxable
from fixtures.akseat import Seat

RULE = "─" * 150
GREY_RULE = f"\x1b[90m{RULE}"
PROMPT = "\x1b[94m>\x1b[39m"
HINT_WORDS = "Auto mode: edits & safe commands auto-approved (shift+tab to cycle)"
HINT_ROW = f"{PROMPT} \x1b[90m{HINT_WORDS}\x1b[39m"
TYPED_ROW = f"{PROMPT} Auto mode: edits"
ASK_DRAFT = ("import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import watch; "
             "print(json.dumps(watch.composer_draft('antigravity', sys.stdin.read())))")


def framed(composer_row, *, rule=RULE, footer=""):
    return f"{rule}\n{composer_row}\n{rule}\n" + (f"{footer}\n" if footer else "")


class FreshAgyComposerHint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def draft(self, pane):
        done = self.home.run(sys.executable, "-c", ASK_DRAFT, str(REPO), input=pane)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)

    def test_grey_hint_reads_empty_and_typed_words_read_as_a_draft(self):
        self.assertEqual(self.draft(framed(HINT_ROW)), "")
        self.assertEqual(self.draft(framed(TYPED_ROW)), "Automode:edits")
        # grey `─` rules still frame both the empty hint and typed text
        self.assertEqual(self.draft(framed(HINT_ROW, rule=GREY_RULE)), "")
        self.assertEqual(self.draft(framed(TYPED_ROW, rule=GREY_RULE)), "Automode:edits")

    def test_any_wording_in_that_grey_is_empty_and_same_words_typed_are_a_draft(self):
        for words in ("Plan mode: edits wait for approval (shift+tab to cycle)",
                      "Accept-edits mode: edits auto-approved (shift+tab to cycle)",
                      "Invented future agy mode wording"):
            with self.subTest(words=words):
                self.assertEqual(self.draft(framed(f"{PROMPT} \x1b[90m{words}\x1b[39m")), "")
        # wrapped grey hint carries SGR 90 onto its second row
        wrapped = f"{PROMPT} \x1b[90mAuto mode: edits & safe commands\n  auto-approved\x1b[39m"
        self.assertEqual(self.draft(framed(wrapped, rule=GREY_RULE)), "")
        # the full hint words typed in the terminal's own colour are a draft
        self.assertEqual(self.draft(framed(f"{PROMPT} {HINT_WORDS}")),
                         HINT_WORDS.replace(" ", ""))

    def test_a_capture_without_colours_reads_as_today(self):
        self.assertEqual(self.draft(framed(f"> {HINT_WORDS}")), HINT_WORDS.replace(" ", ""))


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class FreshAgySeatTakesOwedLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, antigravity="pass")
        akconfig.write(self.home, ["gemini"])

    def screen(self, composer_row, *, left="? for shortcuts"):
        right = "agentkit (Gemini 4 Neon · high)  /agents"
        gap = max(2, 150 - len(left) - len(right))
        footer = (f"\x1b[90m{left}\x1b[39m{' ' * gap}\x1b[94magentkit\x1b[39m "
                  "\x1b[2m(Gemini 4 Neon · high)\x1b[0m  \x1b[94m/agents\x1b[39m")
        return framed(composer_row, rule=GREY_RULE, footer=footer)

    def owe_and_tick(self, seat, line="/effort high"):
        self.home.write(f".agentkit/state/seat-{seat.name}.json", {
            "owed_lines": [{"line": line, "switch": True, "pane": seat.pane, "id": "1"}]})
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_fresh_seat_with_grey_hint_takes_an_owed_line_and_a_typed_draft_holds_it_back(self):
        seat = Seat(self.home, "acme", model="gemini", composer=PROMPT,
                    screen=self.screen(HINT_ROW))
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        self.assertIn("authority: screen", why.out)
        self.assertIn("rule: prompt.composer", why.out)
        self.owe_and_tick(seat)
        self.assertEqual(seat.lines(), ["/effort high"])

        # the same words typed in the terminal's own colour are a draft: nothing is typed onto them
        seat.show(self.screen(TYPED_ROW, left=""))
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        self.assertIn("rule: draft.typed", why.out)
        self.assertIn("evidence:  Auto mode: edits", why.out)
        self.owe_and_tick(seat, "/effort low")
        self.assertEqual(seat.lines(), ["/effort high"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
