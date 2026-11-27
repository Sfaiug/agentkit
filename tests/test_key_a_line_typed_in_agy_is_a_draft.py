"""A line typed into agy 1.5's composer and not sent is a draft, never a turn in flight.

The owner, 25 Nov 2026, on an Antigravity seat: "as soon as I start typing it goes to workign,
even though I have not sent anything."  agy 1.5 draws no footer on a seat, so the composer
itself, its opening rule among the rows read and its closing rule ending them, the background
commands' list under it allowed, tells a typed line.  A spinner over the composer is still a
turn, an empty composer or a fresh seat's muted hint still the prompt, and a composer whose
opening rule is above the rows read still reads nothing.  Each screen is drawn as agy 1.5.18
drew one on a real seat, colours and all, in a seat nobody is in.  Black-box: the program
`AK_BIN` names reads it from outside (tests/fixtures/akseat.py).
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import ESCAPE, FIXTURES, Seat

RULE = "\x1b[38;5;239m" + "─" * 200
MARK = "\x1b[38;5;111m>\x1b[39m"
ECHO = "\x1b[1m\x1b[38;5;111m> say hi in one word\x1b[0m"
REPLY = "  \x1b[38;5;153mHi\x1b[39m"
LONG_REPLY = [f"  \x1b[38;5;153mAcme step {n} done.\x1b[39m" for n in range(14)]
HINT = (f"{MARK} \x1b[38;5;103mAuto mode: edits & safe commands auto-approved "
        "(shift+tab to cycle)\x1b[39m")


def drawn(fixture, *starts):
    """The rows of a capture whose text starts with one of `starts`, as drawn."""
    rows = (FIXTURES / f"antigravity-{fixture}-pane.txt").read_text(encoding="utf-8").splitlines()
    return [row for row in rows if ESCAPE.sub("", row).lstrip().startswith(starts)]


SPINNER, TIP = drawn("1.5-working", "⣷", "└ Tip:")
TRAY = drawn("more-background-draft", "● [", "↓ ")
DRAFT, IN_FLIGHT, IDLE = ("draft.typed", "idle"), ("none", "working"), ("prompt.composer", "idle")
SCREENS = (
    ("a fresh seat", [RULE, f"{MARK} tell me more", RULE], DRAFT),
    ("under a long reply", [ECHO, *LONG_REPLY, RULE, f"{MARK} tell me more", RULE], DRAFT),
    ("spaces after the mark", [ECHO, *LONG_REPLY, RULE, f"{MARK}   x", RULE], DRAFT),
    ("two rows", [ECHO, *LONG_REPLY, RULE, f"{MARK} tell me more", "  more", RULE], DRAFT),
    ("text under a bare mark", [ECHO, REPLY, RULE, MARK, "  later text", RULE], DRAFT),
    ("over background commands",
     [ECHO, REPLY, RULE, f"{MARK} tell me more", RULE, *TRAY, RULE], DRAFT),
    ("under a spinner", [ECHO, SPINNER, TIP, RULE, f"{MARK} tell me more", RULE],
     ("working.spinner", "working")),
    ("an empty composer", [ECHO, REPLY, RULE, MARK, RULE], IDLE),
    ("a fresh seat's muted hint", [RULE, HINT, RULE], IDLE),
    ("opening rule above the rows read",
     [ECHO, RULE, f"{MARK} tell me more", *(f"  acme row {n}" for n in range(14)), RULE],
     IN_FLIGHT),
)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ALineTypedInAgyIsADraft(unittest.TestCase):
    def test_a_composer_holding_text_reads_draft_and_no_turn(self):
        self.assertEqual(len(TRAY), 5)   # the four `●` rows and `↓ 1 more`
        for name, rows, reading in SCREENS:
            with self.subTest(name), Home() as home:
                akconfig.write(home, ["gemini"])
                Seat(home, "acme", model="gemini", composer=">", screen="\n".join(rows) + "\n")
                done = home.ak("orch", "why", "acme")
                self.assertEqual(done.code, 0, done.err)
                data = json.loads((home.path / ".agentkit/state/seat-acme.json").read_text())
                self.assertEqual((data.get("rule"), data.get("word")), reading)


if __name__ == "__main__":
    unittest.main(verbosity=2)
