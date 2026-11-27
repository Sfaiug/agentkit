"""A fresh agy 1.5 composer's grey mode hint is an empty composer, never a line typed.

Before a conversation's first prompt agy 1.5 draws a mode hint in grey (`\x1b[90m`) inside its
empty composer, and typed text in the terminal's own colour.  The colour, never the hint's words,
tells them apart: a grey hint reads as empty (`watch.composer_draft` is `""`, and the seat takes
an owed line as any empty composer does), the same words typed in the terminal's own colour read
as a draft, a grey row hides no draft typed under it, and a plain capture with no colours reads as
today.
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
ASK_WATCH = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import watch\n"
    "def one(kind, pane):\n"
    "    if kind == 'draft': return watch.composer_draft('antigravity', pane)\n"
    "    if kind == 'exact': return watch._composer_rows('antigravity', pane, exact=True)\n"
    "    if kind == 'rows': return watch._composer_rows('antigravity', pane)\n"
    "    if kind == 'stall': return watch.stall_mark('antigravity', pane, None, lambda _: None)\n"
    "    state = watch.classify('antigravity', pane, None, None, {}, 10)\n"
    "    return {'free': watch._free('antigravity', state), 'state': state['state'],\n"
    "            'authority': state['authority'], 'rule': state['rule']}\n"
    "print(json.dumps([one(kind, pane) for kind, pane in json.load(sys.stdin)]))\n")

THEMES = (
    ("terminal", "94", "90", "90"),
    ("light", "38;5;69", "38;5;241", "38;5;253"),
    ("solarized light", "38;5;32", "38;5;66", "38;5;254"),
    ("colorblind-friendly light", "38;5;69", "38;5;241", "38;5;253"),
    ("dark", "38;5;111", "38;5;109", "38;5;238"),
    ("solarized dark", "38;5;32", "38;5;246", "38;5;23"),
    ("colorblind-friendly dark", "38;5;111", "38;5;109", "38;5;238"),
    ("tokyo night", "38;5;111", "38;5;103", "38;5;239"),
    ("light (truecolor)", "38;2;66;133;244", "38;2;95;99;104", "38;2;218;220;224"),
    ("solarized light (truecolor)", "38;2;38;139;210", "38;2;101;123;131", "38;2;238;232;213"),
    ("colorblind-friendly light (truecolor)", "38;2;66;133;244", "38;2;95;99;104", "38;2;218;220;224"),
    ("dark (truecolor)", "38;2;138;180;248", "38;2;154;160;166", "38;2;60;64;67"),
    ("solarized dark (truecolor)", "38;2;38;139;210", "38;2;131;148;150", "38;2;7;54;66"),
    ("colorblind-friendly dark (truecolor)", "38;2;138;180;248", "38;2;154;160;166", "38;2;60;64;67"),
    ("tokyo night (truecolor)", "38;2;122;162;247", "38;2;126;134;173", "38;2;65;72;104"),
)


def framed(composer_row, *, rule=RULE, footer=""):
    return f"{rule}\n{composer_row}\n{rule}\n" + (f"{footer}\n" if footer else "")


class FreshAgyComposerHint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def ask_many(self, cases):
        done = self.home.run(sys.executable, "-c", ASK_WATCH, str(REPO), input=json.dumps(cases))
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)

    def test_grey_hint_reads_empty_and_typed_words_read_as_a_draft(self):
        got = self.ask_many([
            ("draft", framed(HINT_ROW)),
            ("draft", framed(TYPED_ROW)),
            ("draft", framed(HINT_ROW, rule=GREY_RULE)),
            ("draft", framed(TYPED_ROW, rule=GREY_RULE)),
        ])
        self.assertEqual(got, ["", "Automode:edits", "", "Automode:edits"])

    def test_any_wording_in_that_grey_is_empty_and_same_words_typed_are_a_draft(self):
        wordings = ("Plan mode: edits wait for approval (shift+tab to cycle)",
                    "Accept-edits mode: edits auto-approved (shift+tab to cycle)",
                    "Invented future agy mode wording")
        wrapped = f"{PROMPT} \x1b[90mAuto mode: edits & safe commands\n  auto-approved\x1b[39m"
        got = self.ask_many([
            *(("draft", framed(f"{PROMPT} \x1b[90m{words}\x1b[39m")) for words in wordings),
            ("draft", framed(wrapped, rule=GREY_RULE)),
            ("draft", framed(f"{PROMPT} {HINT_WORDS}")),
        ])
        self.assertEqual(got, ["", "", "", "", HINT_WORDS.replace(" ", "")])

    def test_every_built_in_theme_s_muted_hint_reads_empty(self):
        hint = "Plan mode: research & plan only (shift+tab to cycle)"
        gap = " " * (150 - len("? for shortcuts") - len("plan"))
        cases = []
        for _name, mark, muted, frame in THEMES:
            hint_pane = (f"\x1b[{frame}m{RULE}\n\x1b[{mark}m>\x1b[39m \x1b[{muted}m{hint}\n"
                         f"\x1b[{frame}m{RULE}\n")
            footer = f"\x1b[{muted}m? for shortcuts\x1b[39m{gap}\x1b[{mark}mplan\n"
            typed_pane = (f"\x1b[{frame}m{RULE}\n\x1b[{mark}m>\x1b[39m {hint}\n"
                          f"\x1b[{frame}m{RULE}\n")
            cases.extend([("draft", hint_pane), ("draft", f"{hint_pane}{footer}"),
                          ("state", f"{hint_pane}{footer}"), ("draft", typed_pane)])
        got = self.ask_many(cases)
        at_prompt = {"free": True, "state": "at_prompt", "authority": "screen",
                     "rule": "prompt.composer"}
        for at, (name, *_rest) in enumerate(THEMES):
            with self.subTest(theme=name):
                self.assertEqual(got[4 * at:4 * at + 4],
                                 ["", "", at_prompt, hint.replace(" ", "")])

    def test_a_muted_scroll_marker_keeps_a_cropped_draft_from_reading_whole(self):
        rule = "─" * 42
        rows = [f"  Acme_{n:02d}_words Acme_{n + 1:02d}_words" for n in range(48, 64, 2)] + [
            "  Acme_64_words"]
        pane = "\n".join([f"\x1b[90m{rule}", "\x1b[94m>\x1b[39m \x1b[90m↑ 24 more lines\x1b[39m",
                          *rows, f"\x1b[90m{rule}", "\x1b[39m" + " " * 38 + "\x1b[94mplan"])
        self.assertEqual(
            self.ask_many([("rows", pane), ("exact", pane), ("state", pane)]),
            [[row.strip() for row in rows], None,
             {"free": False, "state": "draft", "authority": "screen", "rule": "draft.typed"}])

    def test_a_grey_row_hides_no_draft_typed_under_it(self):
        draft = {"free": False, "state": "draft", "authority": "screen", "rule": "draft.typed"}
        self.assertEqual(self.ask_many([
            ("state", framed(f"{HINT_ROW}\n  acme draft")),
            ("state", HINT_ROW + "\n" + framed(f"{PROMPT} acme draft")),
        ]), [draft, draft])

    def test_fresh_plan_and_accept_edits_footers_are_free_at_prompt(self):
        labels, cases = [], []
        for mode, colour, hint in (
                ("plan", "94", "Plan mode: research & plan only (shift+tab to cycle)"),
                ("accept-edits", "32",
                 "Accept-edits mode: file edits auto-approved (shift+tab to cycle)")):
            for agent in ("", "agentkit"):
                right_plain = f"{mode} · {agent}  /agents" if agent else mode
                right = (f"\x1b[{colour}m{mode}\x1b[2m\x1b[39m · \x1b[0m\x1b[94m{agent}"
                         "\x1b[39m  \x1b[94m/agents") if agent else f"\x1b[{colour}m{mode}"
                gap = " " * (150 - len("? for shortcuts") - len(right_plain))
                footer = f"? for shortcuts\x1b[39m{gap}{right}"
                pane = f"\x1b[90m{RULE}\n{PROMPT} \x1b[90m{hint}\n{RULE}\n{footer}\n"
                labels.append((mode, agent or "none"))
                cases.extend([("draft", pane), ("state", pane)])
        got = self.ask_many(cases)
        want = ["", {"free": True, "state": "at_prompt", "authority": "screen",
                     "rule": "prompt.composer"}]
        for at, (mode, agent) in enumerate(labels):
            with self.subTest(mode=mode, agent=agent):
                self.assertEqual(got[2 * at:2 * at + 2], want)

    def test_bare_mode_words_in_transcript_still_supersede_an_old_stall(self):
        pane = (REPO / "tests/fixtures/antigravity-stall-pane.txt").read_text(encoding="utf-8")
        error = next(row for row in pane.splitlines() if row.startswith("Error ID: "))
        recovered = [pane.replace(error + "\n", f"{error}\n\n  {word}\n", 1)
                     for word in ("Plan", "accept-edits")]
        got = self.ask_many([("stall", pane), *(("stall", text) for text in recovered)])
        self.assertTrue(got[0])
        self.assertEqual(got[1:], [None, None])

    def test_a_capture_without_colours_reads_as_today(self):
        self.assertEqual(self.ask_many([("draft", framed(f"> {HINT_WORDS}"))]),
                         [HINT_WORDS.replace(" ", "")])


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
