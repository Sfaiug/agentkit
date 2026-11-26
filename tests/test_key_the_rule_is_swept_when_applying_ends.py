"""When `Apply` on `c` finishes counting, a light passes once along the header's rule.

The owner (24 Nov 2026): "A job ak can count fills the rule step by step and says "3 of 7" beside
the page name, as an update does; when it ends a light passes once."  Once the count has run
through every session the card named and `c` is drawn again, a light crosses row 2 left to right
in 0.45 s (`motion.SWEEP`), played by the page's own clock: a pointer move does not end it, past
0.45 s every cell is the border's colour again, and a second `Apply` over a seat already holding
the defaults passes the same light.  `Keep`, and motion off (`motion.movable`), light no cell.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) in true
colour at 100 columns over one seat as ak leaves it (tests/fixtures/akseat.py), its clock held
through `AK_MOTION_CLOCK`.  This test fails against `/bin/false`.
"""

import json
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_defaults_apply_to_all import CALM, KEYS, MODELS, key_line, lines

SEAT = "acme-api"
SWEEP = 0.45
SGR = re.compile(r"\x1b\[([0-9;]*)m")


def rule_colours(line):
    """The active foreground SGR of each cell on a rule line from `screen(colours=True)`."""
    colours, fg, at = [], "", 0
    for code in SGR.finditer(line):
        colours.extend([fg] * len(line[at:code.start()]))
        parts = [part or "0" for part in code.group(1).split(";")]
        while parts:
            part = parts.pop(0)
            if part in ("0", "39"):
                fg = ""
            elif part == "38" and parts[:1] in (["2"], ["5"]):
                size = 4 if parts[0] == "2" else 2
                fg, parts = ";".join([part, *parts[:size]]), parts[size:]
            elif part == "48" and parts[:1] in (["2"], ["5"]):
                parts = parts[4 if parts[0] == "2" else 2:]
            elif part.isdigit() and (30 <= int(part) <= 37 or 90 <= int(part) <= 97):
                fg = part
        at = code.end()
    colours.extend([fg] * len(line[at:]))
    return colours


def lit_cells(rule, border):
    """{column: fg} for every cell on `rule` whose colour differs from `border`."""
    return {col: fg for col, fg in enumerate(rule_colours(rule)) if fg != border}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RuleIsSweptWhenApplyingEnds(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, MODELS, workers=["fable"], reviewers=["astra"])
        Seat(self.home, SEAT, model="fable", record=CALM)
        self.clock = self.home.root / "clock"
        self.at(1000.0)

    def at(self, seconds):
        """Hold ak's motion clock at `seconds` via an atomic swap."""
        self.now = seconds
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def open_c(self, env=None):
        """Open `ak` in a 100x30 terminal on the held clock, go to `c`, and wait until at rest."""
        term = Terminal(self.home, size=(100, 30),
                        env={"AK_MOTION_CLOCK": str(self.clock), **(env or {})})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("c config")
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == KEYS)
        self.at(self.now + 10.0)
        return term

    def rule(self, term):
        return term.screen(colours=True).splitlines()[1]

    def wait_coloured(self, term, test, why, bound=30):
        deadline = time.monotonic() + bound
        while True:
            shown = term.screen(colours=True)
            if test(shown):
                return shown
            if time.monotonic() > deadline:
                raise AssertionError(f"{why}; screen:\n{shown!r}")
            time.sleep(0.05)

    def wait_rule(self, term, test, why, bound=30):
        return self.wait_coloured(term, lambda s: test(s.splitlines()[1]), why, bound).splitlines()[1]

    def apply_on(self, term):
        """Open `a` on `c`, pick `Apply`, and wait for `c` to draw back."""
        term.keys("a")
        term.wait(lambda screen: {"  No session restarts.", "  × Apply"} <= set(lines(screen)))
        term.keys("Down")
        term.wait(lambda screen: "› × Apply" in lines(screen))
        term.keys("Enter")
        return term.wait(lambda screen: "a apply to all sessions" in key_line(screen)
                         and "  × Apply" not in lines(screen))

    def move_pointer_to(self, term, label):
        """Move the pointer onto `label`'s row and wait for the highlight to land there."""
        shown = lines(term.screen())
        row = next(n for n, line in enumerate(shown, 1) if label in line)
        term.type(f"\x1b[<35;5;{row}M")
        term.wait(lambda screen: any(line.startswith(f"› {label}") for line in lines(screen)))

    def test_apply_sweeps_the_rule_through_pointer_moves_and_on_repeat(self):
        term = self.open_c()
        rest = rule_colours(self.rule(term))
        self.assertEqual(len(rest), 100)
        border = rest[0]
        self.assertTrue(border, "expected true-colour border")
        self.assertEqual(set(rest), {border})

        # First Apply: seat changes from CALM to defaults.
        began = self.now
        self.apply_on(term)
        self.at(began + SWEEP / 2)
        half = self.wait_rule(
            term,
            lambda r: (lit := lit_cells(r, border)) and 0 not in lit and len(lit) < 100,
            "no light passed along the rule at half of SWEEP")
        lit = lit_cells(half, border)
        self.assertEqual(SGR.sub("", half), "─" * 100)
        self.assertTrue(0 < len(lit) < 100)

        # Pointer move and keys that stay on `c` while passing: same cells stay lit.
        def stayed_lit(pred, why):
            self.wait_coloured(
                term,
                lambda s: pred(SGR.sub("", s)) and lit_cells(s.splitlines()[1], border) == lit,
                why)

        self.move_pointer_to(term, "Models")
        stayed_lit(lambda s: any(l.startswith("› Models") for l in lines(s)),
                   "pointer move onto Models did not keep the same cells lit")
        term.keys("Down")
        stayed_lit(lambda s: any(l.startswith("› Subscriptions") for l in lines(s)),
                   "Down on config did not keep the same cells lit")
        term.type("\x1b[<35;5;1M")
        stayed_lit(lambda s: "›" not in s and "a apply to all sessions" in key_line(s),
                   "pointer onto header did not keep the same cells lit")
        term.keys("Space")
        stayed_lit(lambda s: any(l.startswith("› Subscriptions") for l in lines(s)),
                   "Space from header did not keep the same cells lit")

        # Past SWEEP: every cell of the rule is back to the border's colour.
        self.at(began + SWEEP + 0.05)
        self.wait_rule(term, lambda r: not lit_cells(r, border),
                       "rule stayed lit past SWEEP")

        # Seat now already has the defaults; Apply again sweeps the same light.
        record = json.loads((self.home.path / f".agentkit/state/session-{SEAT}.json").read_text())
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("fable", ["fable"], ["astra"]))
        began = self.now + 1.0
        self.at(began)
        self.apply_on(term)
        self.at(began + SWEEP / 2)
        again = self.wait_rule(
            term,
            lambda r: (c := lit_cells(r, border)) and 0 not in c and len(c) < 100,
            "no light passed on second Apply over a seat already at defaults")
        self.assertEqual(lit_cells(again, border), lit)
        self.at(began + SWEEP + 0.05)
        self.wait_rule(term, lambda r: not lit_cells(r, border),
                       "rule stayed lit past SWEEP on second Apply")

        # Opening a second Apply card mid-sweep clears the light on the card and after Keep/Esc.
        for answer in ("Enter", "Escape"):
            with self.subTest(cancel_mid_sweep=answer):
                began = self.now + 1.0
                self.at(began)
                self.apply_on(term)
                self.at(began + SWEEP / 2)
                self.wait_rule(
                    term,
                    lambda r: (c := lit_cells(r, border)) and 0 not in c and len(c) < 100,
                    "no light passed before opening second card")
                term.keys("a")
                self.wait_coloured(
                    term,
                    lambda s: "› ✓ Keep" in SGR.sub("", s) and not lit_cells(s.splitlines()[1], border),
                    "second Apply card inherited the previous sweep")
                term.keys(answer)
                self.wait_coloured(
                    term,
                    lambda s: "a apply to all sessions" in key_line(SGR.sub("", s))
                    and "× Apply" not in SGR.sub("", s)
                    and not lit_cells(s.splitlines()[1], border),
                    f"{answer} on second Apply card left the rule lit")

    def test_keep_and_motion_off_light_no_cell_of_the_rule(self):
        # After Keep in true colour, no cell of the rule is ever lit.
        term = self.open_c()
        border = rule_colours(self.rule(term))[0]
        self.assertTrue(border)
        began = self.now
        term.keys("a")
        term.wait(lambda screen: "› ✓ Keep" in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: key_line(screen) == KEYS and "  × Apply" not in lines(screen))
        self.assertEqual(lit_cells(self.rule(term), border), {})
        self.at(began + SWEEP / 2)
        self.move_pointer_to(term, "Models")
        self.assertEqual(lit_cells(self.rule(term), border), {})

        # With motion off (NO_COLOR and 8-colour terminal), Apply lights no cell.
        for label, env in (("no_color", {"NO_COLOR": "1"}),
                           ("eight_colour", {"TERM": "xterm", "COLORTERM": ""})):
            with self.subTest(motion_off=label):
                self.at(self.now + 10.0)
                off = self.open_c(env=env)
                rest = rule_colours(self.rule(off))
                self.assertEqual(len(set(rest)), 1)
                off_border = rest[0]
                began = self.now
                self.apply_on(off)
                self.assertEqual(lit_cells(self.rule(off), off_border), {})
                self.at(began + SWEEP / 2)
                self.move_pointer_to(off, "Models")
                self.assertEqual(lit_cells(self.rule(off), off_border), {})


if __name__ == "__main__":
    unittest.main()
