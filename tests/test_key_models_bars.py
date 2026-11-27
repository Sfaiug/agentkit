"""Under the role lines, `r recommended` on `c` draws the highlighted role as bars: its choices,
then as many of its `others`, best first, as fill five places, shaded, side by side, cheapest on
the left and the dearer taller; on each its cost, under it its quality, its name wrapped at words
in its column, on 40 cells and on 100, and its effort, and under a shaded one, standing in whole
shaded cells and never over a dearer bar, its why led by `░`;
`━` under the name of the row the role uses.  ↑↓ draw another role's bars, and on 40 cells,
its costs $100 and more, all five.  On a page too short for every role's line the heading stays
over the roles it shows, under a role with no numbers too.

Black-box: `AK_BIN` in a terminal of 40 rows (tests/fixtures/akterm.py), a fake harness running
three of the releases, each for a role of [defaults], the boards held as
tests/test_key_role_choices.py writes them; judged by the screen.  Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_role_choices import hold

# Release, name, quality in every role and cost a task, each at `high`, cheapest first
ROWS = [("acme-low-1", "Acme Low 1", 85, 1),          # far below: an other the five leave out
        ("acme-base-1", "Acme Base 1", 92, 2),
        ("acme-long-1", "Acme Long Name 1", 92.5, 3),  # close to Base, its name wider than a column
        ("acme-step-1", "Acme Step 1", 96, 4),
        ("acme-dear-1", "Acme Dear 1", 95, 6),         # beaten by Step
        ("acme-top-1", "Acme Top 1", 100, 8)]
# What each role draws, left to right: name, quality, cost, shaded with its why or solid (None)
BARS = [("Acme Base 1", "92.0", "≈$2.00", None), ("Acme Long Name 1", "92.5", "≈$3.00", "░ close"),
        ("Acme Step 1", "96.0", "≈$4.00", None), ("Acme Dear 1", "95.0", "≈$6.00", "░ beaten"),
        ("Acme Top 1", "100.0", "≈$8.00", None)]
HEADING = "{} · three choices · two more shaded"
# [defaults]: each role runs another of the choices
USES = {"orchestrator": "Acme Step 1", "executor": "Acme Top 1", "reviewer": "Acme Base 1"}
CONFIGURED = {"step": "acme-step-1", "top": "acme-top-1", "base": "acme-base-1"}
# The eighths of a cell each glyph of a bar stands: whole, solid or shaded, else its top
STANDS = {"█": 8, "░": 8, **{glyph: n for n, glyph in enumerate("▁▂▃▄▅▆▇", 1)}}


def bars(text, word):
    """The bars under the heading `word` begins, left to right, each {name, lines it takes,
    quality, cost, eighths it stands, glyphs it stands in, shaded, why from its `░` on, effort,
    marked}, read down to
    the blank line under them; a column reaches from its bar's left edge to the next bar's."""
    shown = [line.rstrip() for line in text.split("\n")]
    head = next(n for n, line in enumerate(shown) if line.strip().startswith(word + " · "))
    standing = lambda line: any(c in STANDS for c in line)
    first = next(n for n in range(head + 1, len(shown)) if standing(shown[n]))
    foot = next(n for n in range(first, len(shown)) if not standing(shown[n + 1]))
    last = next(n for n in range(foot, len(shown)) if not shown[n])
    starts = [found.start() for found in re.finditer(r"\S+", shown[foot])]
    found = []
    for start, end in zip(starts, [*starts[1:], None]):
        chart = [line[start:end].strip() for line in shown[head + 1:foot + 1]]
        under = [cell for line in shown[foot + 1:last] for cell in [line[start:end].strip()] if cell]
        stands = [STANDS.get(cell[0], 0) if len(set(cell)) == 1 else 0 for cell in chart]
        top = next(n for n, eighths in enumerate(stands) if eighths)
        quality, *rest = under
        at = next((n for n, cell in enumerate(rest) if cell.startswith("░")), len(rest))
        rest, why = rest[:at], " ".join(rest[at:]) or None
        shaded = any("░" in cell for cell in chart)
        effort = rest.pop()
        marked = bool(rest) and set(rest[-1]) == {"━"}
        names = rest[:-1] if marked else rest
        found.append({"name": " ".join(names), "lines": names, "quality": quality,
                      "cost": chart[top - 1], "eighths": sum(stands), "shaded": shaded,
                      "glyphs": {cell[0] for cell, eighths in zip(chart, stands) if eighths},
                      "why": why, "effort": effort, "marked": marked})
    return found


def drawn(text, word):
    """What `word`'s bars say: each one's (name, quality, cost, why, effort), left to right,
    whether each with a why is shaded and only those, whether each stands taller than the one on
    its left, and the names marked; None before they are drawn."""
    try:
        found = bars(text, word)
    except (StopIteration, ValueError, IndexError):
        return None
    return ([(bar["name"], bar["quality"], bar["cost"], bar["why"], bar["effort"])
             for bar in found],
            all(bar["shaded"] == (bar["why"] is not None) for bar in found),
            all(left["eighths"] < right["eighths"] for left, right in zip(found, found[1:])),
            [bar["name"] for bar in found if bar["marked"]])


def want(word):
    """BARS, cheapest on the left and the dearer taller, the row `word`'s role uses marked."""
    return [(*bar, "high") for bar in BARS], True, True, [USES[word]]


def held(home, rows):
    """`home` holding the boards of `rows` (ROWS's kind) and the harness and [defaults] USES
    names."""
    names = {release: name for release, name, *_ in rows}
    fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
        f"{release}\t{names[release]}\thigh\n" for release in CONFIGURED.values()))
    akconfig.write(home, {name: {"harness": "claude", "model": release}
                          for name, release in CONFIGURED.items()},
                   orchestrator="step", workers=["top"], reviewers=["base"])
    hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                for release, name, quality, cost in rows])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsBars(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        held(cls.home, ROWS)

    def opened(self, home, width=100):
        """`r` on `c` over `home` in a window of its own, 40 rows high."""
        term = Terminal(home, size=(width, 40), env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term

    def models(self, width=100):
        """`opened` over the class's home, and the screen once the orchestrator's bars are drawn
        as `want` has them."""
        term = self.opened(self.home, width)
        return term, term.wait(lambda screen: drawn(screen, "orchestrator") == want("orchestrator"))

    def each_role(self, rows, width, said, want):
        """`r` over a home holding `rows` (`held`), `width` cells wide, until each role's bars,
        ↓ drawing the next, say what `want` of its word has `said` of them."""
        home = Home()
        self.addCleanup(home.close)
        held(home, rows)
        term = self.opened(home, width)
        for n, word in enumerate(USES):
            if n:
                term.keys("Down")

            def says(screen):
                try:
                    return said(bars(screen, word)) == want(word)
                except (StopIteration, ValueError, IndexError):
                    return False
            term.wait(says)

    def test_the_role_you_are_on_draws_its_choices_then_others_shaded_the_row_in_use_marked(self):
        _, shown = self.models()
        self.assertIn("\n  " + HEADING.format("orchestrator") + "\n", shown)

    def test_a_name_too_long_for_its_column_wraps_at_words_on_40_cells_and_on_100(self):
        for width in (40, 100):
            with self.subTest(width=width):
                shown = self.models(width)[1]
                self.assertGreater(len(bars(shown, "orchestrator")[1]["lines"]), 1, shown)

    def test_a_shaded_bar_stands_in_whole_shaded_cells_never_over_a_dearer_one(self):
        # 7 cells for $8: Long Name's $3 and Dear's $6 end in a part of a cell, and Long Name's
        # whole third cell would stand over Step's 2.75 at $3.20
        def said(found):
            stands = [bar["eighths"] for bar in found]
            return ([bar["cost"] for bar in found],
                    [bar["glyphs"] for bar in found if bar["shaded"]], stands == sorted(stands))
        costs = ["≈$2.00", "≈$3.00", "≈$3.20", "≈$6.00", "≈$8.00"]
        self.each_role([(*row[:-1], 3.2 if row[1] == "Acme Step 1" else row[-1]) for row in ROWS],
                       100, said, lambda word: (costs, [{"░"}, {"░"}], True))

    def test_up_and_down_draw_another_roles_bars(self):
        term, _ = self.models()
        for key, word in (("Down", "executor"), ("Down", "reviewer"), ("Up", "executor"),
                          ("Up", "orchestrator")):
            term.keys(key)
            term.wait(lambda screen: drawn(screen, word) == want(word))

    def test_a_page_too_short_for_every_role_keeps_the_heading_over_the_roles_it_shows(self):
        term = Terminal(self.home, size=(40, 12), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("› orchestrator")
        term.keys("Down", "Down")
        # waited for, as the first drawing has no numbers yet: the boards land after it
        term.wait(lambda screen: [line.split()[:2] for line in screen.split("\n")[2:7]] == [
            ["quality", "$"], ["executor", "100.0"], ["Acme", "Top"],
            ["›", "reviewer"], ["Acme", "Base"]])

    def test_the_heading_stays_over_them_under_a_role_with_no_numbers_too(self):
        """The orchestrator's row on no board, so the heading stands under its lines, and the
        reviewer's name on two lines, so the page showing it starts past the heading."""
        rows = [(release, "Acme Long Reviewer Model Name 1.0 Pro" if release == "acme-base-1"
                 else name, *rest) for release, name, *rest in ROWS]
        home = Home()
        self.addCleanup(home.close)
        held(home, rows)
        hold(home, [(release, name, "high", quality / 100 - 0.1, cost)
                    for release, name, quality, cost in rows if release != "acme-step-1"])
        term = Terminal(home, size=(40, 12), env=ENV)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait(lambda screen: "not on the boards" in screen and "100.0" in screen)
        term.keys("Down", "Down")
        term.wait(lambda screen: [line.split()[:2] for line in screen.split("\n")[2:7]] == [
            ["quality", "$"], ["Acme", "Top"], ["›", "reviewer"], ["Acme", "Long"],
            ["Pro", "high"]])

    def test_on_40_cells_costs_of_100_and_more_draw_all_five_on_the_screen(self):
        # each cost fiftyfold, in whole dollars from $100 on
        costs = ["≈$100", "≈$150", "≈$200", "≈$300", "≈$400"]
        self.each_role([(*row, 50 * cost) for *row, cost in ROWS], 40, lambda found: (
            [(bar["name"], bar["cost"]) for bar in found],
            [bar["name"] for bar in found if bar["marked"]]), lambda word: (
            [(name, cost) for (name, *_), cost in zip(BARS, costs)], [USES[word]]))


if __name__ == "__main__":
    unittest.main()
