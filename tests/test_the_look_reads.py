"""The look reads on a terminal's own background exactly where its rule holds, every colour there
the owner's but the background, the highlight's and the border's (agentkit/reads.py).

The owner, 20 Nov 2026: ak "just sits on top of" the terminal's background; of the highlight
there, 22 Nov: "Follow the terminal".  The rule, computed here from `themes.ROLES`, never by
reads.py, in the theme the background fits (luma past half way, white): each text role has with
it what it has with the theme's own, or 3 where that is less; and the background moved `k` times
what the theme's selection is from its own, at the largest `k` in hundredths up to 1, is a
highlight each text role has with it what it has with the selection, or 3, and which has with
the background what the selection has with the theme's, or white's with white.  The border moves
whole.  A breath on the highlight runs to it.  In process, over a 9 x 9 x 9 grid of the colour
cube and five terminals' own.
"""

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
NAMED = ("24272d", "282a36", "002b36", "fdf6e3", "203040")    # terminals' own, neither theme's
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


def text_reads(on, ground, theme):
    """Each text role has with `on` what it has with the theme's `ground`, or 3."""
    return all(contrast(ROLES[role][theme], on) >=
               min(contrast(ROLES[role][theme], ROLES[ground][theme]), 3) for role in TEXT)


def lights(rgb, k):
    """Whether the highlight at `k` holds on `rgb`, in the theme it fits."""
    theme = fits(rgb)
    lit = moved(rgb, "selection", theme, k)
    least = min(contrast(ROLES["selection"][theme], ROLES["background"][theme]),
                contrast(ROLES["selection"][WHITE], ROLES["background"][WHITE]))
    return text_reads(lit, "selection", theme) and contrast(lit, rgb) >= least


class TheLookReads(unittest.TestCase):
    def test_it_reads_exactly_where_the_rule_holds(self):
        for rgb in BACKGROUNDS:
            found, theme = reads.look(rgb, fits(rgb)), fits(rgb)
            k = next((n / 100 for n in range(100, 0, -1) if lights(rgb, n / 100)), None)
            with self.subTest(background=rgb):     # at the largest `k`, else nowhere
                self.assertEqual(found and found[0],
                                 k if text_reads(rgb, "background", theme) else None)
                if found:
                    self.assertEqual(found[1], {
                        **{role: shades[theme] for role, shades in ROLES.items()},
                        "background": rgb, "selection": moved(rgb, "selection", theme, k),
                        "border": moved(rgb, "border", theme, 1)})

    def test_a_breath_on_the_highlight_runs_to_it_and_stays_apart_from_it(self):
        # its dimmest tone, as the working dot on the highlighted row draws it: half way from
        # the accent to the highlight
        read = [found[1] for rgb in BACKGROUNDS if (found := reads.look(rgb, fits(rgb)))]
        self.assertGreater(len(read), len(NAMED))
        for look in read:
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
                             (1, {role: shades[theme] for role, shades in ROLES.items()}))

    def test_it_reads_on_terminals_own_backgrounds(self):
        for rgb in NAMED:
            self.assertIsNotNone(reads.look(rgb, fits(rgb)), rgb)


if __name__ == "__main__":
    unittest.main()
