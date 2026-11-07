"""Under the role lines, `r recommended` on `c` draws the role `▸` is on as bars: its choices,
then as many of its `others`, best first, as fill five places, shaded, side by side, cheapest on
the left and the dearer taller; on each its cost, under it its quality, its name wrapped at words
in its column, on 40 cells and on 100, and its effort, and under a shaded one its why; `━` under
the name of the row the role uses.  ↑↓ draw another role's bars; `ak models` prints every role's
in turn under its role lines, and on 40 cells, where five places leave its labels too little
room, the last of `others` gives its place up and every line stays on the screen.

Black-box: `AK_BIN` in a terminal of 40 rows (tests/fixtures/akterm.py) and as `ak models`, a
fake harness running three of the releases, each for a role of [defaults], the boards held as
tests/test_key_role_choices.py writes them; judged by the screen and the output.  Fails against
/bin/false.
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
BARS = [("Acme Base 1", "92.0", "≈$2.00", None), ("Acme Long Name 1", "92.5", "≈$3.00", "close"),
        ("Acme Step 1", "96.0", "≈$4.00", None), ("Acme Dear 1", "95.0", "≈$6.00", "beaten"),
        ("Acme Top 1", "100.0", "≈$8.00", None)]
HEADING = "{} · three choices · two more shaded"
# [defaults]: each role runs another of the choices
USES = {"orchestrator": "Acme Step 1", "executor": "Acme Top 1", "reviewer": "Acme Base 1"}
CONFIGURED = {"step": "acme-step-1", "top": "acme-top-1", "base": "acme-base-1"}
# The eighths of a cell each glyph of a bar stands: whole, solid or shaded, else its top
STANDS = {"█": 8, "░": 8, **{glyph: n for n, glyph in enumerate("▁▂▃▄▅▆▇", 1)}}


def bars(text, word):
    """The bars under the heading `word` begins, left to right, each {name, lines it takes,
    quality, cost, eighths it stands, shaded, why, effort, marked}, read down to the blank line
    under them; a column reaches from its bar's left edge to the next bar's."""
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
        shaded = any("░" in cell for cell in chart)
        why = rest.pop() if shaded else None
        effort = rest.pop()
        marked = bool(rest) and set(rest[-1]) == {"━"}
        names = rest[:-1] if marked else rest
        found.append({"name": " ".join(names), "lines": names, "quality": quality,
                      "cost": chart[top - 1], "eighths": sum(stands), "shaded": shaded,
                      "why": why, "effort": effort, "marked": marked})
    return found


def drawn(text, word):
    """What `word`'s bars say: each one's (name, quality, cost, why, effort), left to right,
    whether each stands taller than the one on its left, and the names marked; None before
    they are drawn."""
    try:
        found = bars(text, word)
    except (StopIteration, ValueError, IndexError):
        return None
    return ([(bar["name"], bar["quality"], bar["cost"], bar["why"], bar["effort"])
             for bar in found],
            all(left["eighths"] < right["eighths"] for left, right in zip(found, found[1:])),
            [bar["name"] for bar in found if bar["marked"]])


def want(word):
    """BARS, cheapest on the left and the dearer taller, the row `word`'s role uses marked."""
    return [(*bar, "high") for bar in BARS], True, [USES[word]]


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

    def models(self, width=100):
        """`r` on `c` in a window of its own, 40 rows high, and the screen once the
        orchestrator's bars are drawn as `want` has them."""
        term = Terminal(self.home, size=(width, 40), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term, term.wait(lambda screen: drawn(screen, "orchestrator") == want("orchestrator"))

    def test_the_role_you_are_on_draws_its_choices_then_others_shaded_the_row_in_use_marked(self):
        _, shown = self.models()
        self.assertIn("\n  " + HEADING.format("orchestrator") + "\n", shown)

    def test_a_name_too_long_for_its_column_wraps_at_words_on_40_cells_and_on_100(self):
        for width in (40, 100):
            with self.subTest(width=width):
                shown = self.models(width)[1]
                self.assertGreater(len(bars(shown, "orchestrator")[1]["lines"]), 1, shown)

    def test_up_and_down_draw_another_roles_bars(self):
        term, _ = self.models()
        for key, word in (("Down", "executor"), ("Down", "reviewer"), ("Up", "executor"),
                          ("Up", "orchestrator")):
            term.keys(key)
            term.wait(lambda screen: drawn(screen, word) == want(word))

    def test_ak_models_prints_every_roles_bars_in_turn_under_its_role_lines(self):
        done = self.home.ak("models", env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        shown, heads = done.out.split("\n"), ["  " + HEADING.format(word) for word in USES]
        self.assertEqual([line for line in shown if line in heads], heads, done.out)
        self.assertLess(next(n for n, line in enumerate(shown)
                             if line.strip().startswith("quality ")), shown.index(heads[0]))
        for word in USES:
            self.assertEqual(drawn(done.out, word), want(word), done.out)

    def test_on_40_cells_labels_too_wide_for_five_places_take_one_and_stay_on_the_screen(self):
        with Home() as home:      # each cost fiftyfold, $100 to $400: eight cells on its top
            held(home, [(*row, 50 * cost) for *row, cost in ROWS])
            done = home.ak("models", env={**ENV, "COLUMNS": "40"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual([line for line in done.out.split("\n") if len(line) > 40], [], done.out)
        for word in USES:
            self.assertEqual([bar["name"] for bar in bars(done.out, word)],
                             ["Acme Base 1", "Acme Step 1", "Acme Dear 1", "Acme Top 1"], done.out)


if __name__ == "__main__":
    unittest.main()
