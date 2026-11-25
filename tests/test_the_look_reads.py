"""The look reads on a terminal's own background exactly where its rule holds, every colour there
the owner's but the background, the highlight's and the border's (agentkit/reads.py).

The owner, 20 Nov 2026: ak "just sits on top of" the terminal's background; of the highlight
there, 22 Nov: "Follow the terminal".  The rule, computed here from `themes.ROLES`, never by
reads.py, in the theme the background fits (luma past half way, white): each text role has with
it what it has with the theme's own, or 3 where that is less; and the background moved `k` times
what the theme's selection is from its own, at the largest `k` up to 1, every colour that move
passes through tried, is a highlight each text role has with it what it has with the selection,
or 3, and which has with the background what the selection has with the theme's, or white's
with white.  The border moves whole.  A breath on the highlight runs to it.  In process, over a
9 x 9 x 9 grid of the colour cube and six terminals' own.
"""

from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import motion, reads, terminal
from agentkit.themes import BLACK, ROLES, WHITE

TEXT = ("text", "muted", "dim", "accent", "success", "warning", "error", "info", "special")
# terminals' own, neither theme's: the last two have a highlight only between hundredths of `k`
NAMED = ("24272d", "282a36", "002b36", "fdf6e3", "203040", "402080")
STEPS = [round(n * 255 / 8) for n in range(9)]
BACKGROUNDS = [bytes((r, g, b)).hex() for r in STEPS for g in STEPS for b in STEPS] + list(NAMED)


@lru_cache(maxsize=None)
def luminance(rgb):
    return sum(share * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
               for share, c in zip((0.2126, 0.7152, 0.0722), (b / 255 for b in bytes.fromhex(rgb))))


def contrast(one, other):
    low, high = sorted((luminance(one), luminance(other)))
    return (high + 0.05) / (low + 0.05)


def fits(rgb):
    luma = sum(w * c / 255 for w, c in zip((0.2126, 0.7152, 0.0722), bytes.fromhex(rgb)))
    return WHITE if luma > 0.5 else BLACK


def moved(rgb, role, theme, k):
    return bytes(max(0, min(255, round(c + k * (to - base)))) for c, to, base in zip(
        *map(bytes.fromhex, (rgb, ROLES[role][theme], ROLES["background"][theme])))).hex()


def move(rgb, theme):
    """Each highlight `rgb` moved toward the theme's passes through, from `k` 1 down, exactly:
    the one at 1, at each `k` where a channel is half way between two values, and between."""
    turns = {Fraction(0), Fraction(1)}
    for at, to, base in zip(*map(bytes.fromhex, (rgb, ROLES["selection"][theme],
                                                  ROLES["background"][theme]))):
        turns |= {(Fraction(2 * value + 1, 2) - at) / (to - base)
                  for value in range(min(at, at + to - base), max(at, at + to - base))}
    turns = sorted(turns, reverse=True)
    return [moved(rgb, "selection", theme, k)
            for high, low in zip(turns, turns[1:]) for k in (high, (high + low) / 2)]


def text_reads(on, ground, theme):
    """Each text role has with `on` what it has with the theme's `ground`, or 3."""
    return all(contrast(ROLES[role][theme], on) >=
               min(contrast(ROLES[role][theme], ROLES[ground][theme]), 3) for role in TEXT)


def lights(rgb, lit):
    """Whether `lit` is a highlight on `rgb`, in the theme it fits."""
    theme = fits(rgb)
    least = min(contrast(ROLES["selection"][theme], ROLES["background"][theme]),
                contrast(ROLES["selection"][WHITE], ROLES["background"][WHITE]))
    return text_reads(lit, "selection", theme) and contrast(lit, rgb) >= least


class TheLookReads(unittest.TestCase):
    def test_it_reads_exactly_where_the_rule_holds(self):
        read = 0
        for rgb in BACKGROUNDS:
            theme = fits(rgb)
            # the first along the move, so no highlight further along it holds
            lit = next((lit for lit in move(rgb, theme) if lights(rgb, lit)), None) \
                if text_reads(rgb, "background", theme) else None
            with self.subTest(background=rgb):
                self.assertEqual(reads.look(rgb, theme), lit and {
                    **{role: shades[theme] for role, shades in ROLES.items()},
                    "background": rgb, "selection": lit, "border": moved(rgb, "border", theme, 1)})
            read += bool(lit)
        self.assertGreater(read, len(NAMED))

    def test_a_breath_on_the_highlight_runs_to_it_and_stays_apart_from_it(self):
        # its dimmest tone, as the working dot on the highlighted row draws it: half way from
        # the accent to the highlight
        for look in filter(None, (reads.look(rgb, fits(rgb)) for rgb in BACKGROUNDS)):
            lit, accent = look["selection"], look["accent"]
            with self.subTest(background=look["background"]), \
                    patch.object(terminal, "LOOK", look), \
                    patch.object(terminal, "colour_depth", return_value=24):
                drawn = motion.tinted("●", "working", motion.DIMMER, bright=True)
                tone = bytes(map(int, re.search(r"38;2;(\d+);(\d+);(\d+)", drawn).groups()))
                self.assertEqual(tone, bytes(round((a + b) / 2) for a, b in zip(
                    *map(bytes.fromhex, (accent, lit)))))
                self.assertGreaterEqual(contrast(tone.hex(), lit), 1.3)

    def test_on_black_and_white_every_colour_is_the_owners(self):
        for rgb, theme in (("000000", BLACK), ("ffffff", WHITE)):
            self.assertEqual(reads.look(rgb, theme),
                             {role: shades[theme] for role, shades in ROLES.items()})

    def test_it_reads_on_terminals_own_backgrounds(self):
        for rgb in NAMED:
            self.assertIsNotNone(reads.look(rgb, fits(rgb)), rgb)


if __name__ == "__main__":
    unittest.main()
