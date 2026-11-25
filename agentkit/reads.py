"""Whether ak's one look reads on a terminal's own background, and its colours there.  It hides
READS, SHOWS and how far the highlight moves, `k`: a screen asks only for a role
(`terminal.colour`).  The owner, 20 Nov 2026: ak "just sits on top of" the terminal's
background; of the highlight there, 22 Nov: "Follow the terminal".  Where the look reads a
screen sets no background of its own (`terminal._painted`); elsewhere it is painted in its
theme.  The rule is tests/test_the_look_reads.py's.
"""

from functools import lru_cache

from .themes import ROLES, WHITE

READS = 3       # the contrast text needs, where its theme gives it more: WCAG's for large text
TEXT = ("text", "muted", "dim", "accent", "success", "warning", "error", "info", "special")


@lru_cache(maxsize=None)
def _luminance(rgb):
    """WCAG's relative luminance of `rgb`, rrggbb."""
    return sum(share * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
               for share, c in zip((0.2126, 0.7152, 0.0722), (b / 255 for b in bytes.fromhex(rgb))))


def contrast(one, other):
    """WCAG's contrast of two colours, rrggbb: 1 to 21."""
    low, high = sorted(map(_luminance, (one, other)))
    return (high + 0.05) / (low + 0.05)


# What a highlight needs with what it is on, where its theme gives it more: what the white theme's
# has with white, the least the owner drew.
SHOWS = contrast(ROLES["selection"][WHITE], ROLES["background"][WHITE])


def _moved(background, role, theme, k):
    """`background` moved, channel by channel, `k` times what `role` is from the theme's own."""
    return bytes(max(0, min(255, round(at + k * (to - base)))) for at, to, base in zip(
        *(bytes.fromhex(rgb) for rgb in (background, ROLES[role][theme],
                                         ROLES["background"][theme])))).hex()


def look(background, theme):
    """(`k`, each role's colour) on a terminal whose own background is `background`, rrggbb, in
    the `theme` it fits, None where the look does not read on it: each text role has there what
    it has on the theme's own background, or READS, and on a highlight, the background moved `k`
    times what the theme's selection is from its own, what it has on that selection, or READS,
    the highlight having with the background what the selection has, or SHOWS."""
    own = {role: shades[theme] for role, shades in ROLES.items()}

    def keeps(on, theirs):
        return all(contrast(own[role], on) >= min(contrast(own[role], theirs), READS)
                   for role in TEXT)
    shows = min(contrast(own["selection"], own["background"]), SHOWS)
    if keeps(background, own["background"]):
        for k in (n / 100 for n in range(100, 0, -1)):
            lit = _moved(background, "selection", theme, k)
            if contrast(lit, background) >= shows and keeps(lit, own["selection"]):
                return k, {**own, "background": background, "selection": lit,
                           "border": _moved(background, "border", theme, 1)}
    return None
