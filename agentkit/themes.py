"""The owner (20 Nov 2026): "I dont like that the user can switch and choose. First off I dont want
2 themes, I just want one, and the background of the terminal which the user has in its setting
should be used, and ak just sits on top of that."  On a light terminal: "Adapt by itself".

So ak has one look in two shades, the columns of ROLES, and every colour it draws is a role's.
Only the terminal picks: a menu whose terminal answers what its background is draws in the
shades that background fits and keeps the answer (`terminal.sense`); whatever cannot ask -- a
listing, a seat's bar, the popup's border -- and a menu whose terminal does not answer draw in
the shades the answer last kept fits (`fits`), black's until one is kept.
tests/test_boundaries.py counts an RGB written anywhere but here.  Run bare, `themes.py <kept>
<role>...`, it says each role's colour as tmux draws it (`terminal.colour`'s `tmux`), on one
line: `Ctrl-b m`'s job asks them as the key is pressed (orch.FLOAT), and one start of Python
that imports no more than this holds the popup up least.
"""

import sys

WHITE, BLACK = 0, 1     # each shade's column: white's for a light background, black's for any other
KEPT = "background"     # the file in ak's state the last answer is kept in: `light`, else dark
ROLES = {
    "background": ("ffffff", "000000"),
    "surface": ("f4f6fa", "111519"),
    "selection": ("dcecff", "08305d"),
    "border": ("b1b8c0", "3a3f46"),
    "text": ("181c22", "e2e8ef"),
    "muted": ("535962", "acb4bd"),
    "dim": ("6f757e", "868d97"),
    "accent": ("0067c6", "4da3ff"),
    "success": ("007935", "33b65f"),
    "warning": ("8e5e00", "d79200"),
    "error": ("c52a2f", "fe756f"),
    "info": ("00747d", "00b0bf"),
    "special": ("a23baa", "da7de0"),
    "on-accent": ("ffffff", "000000"),
}
# A light that moves says only that it moves, so it is no role's: from its head back, the roles
# that say where a thing stands in the spectrum's order, each shade's own rainbow (motion.lit).
RAINBOW = ("error", "warning", "success", "info", "accent", "special")


def fits(path):
    """The shades the answer kept at `path` fits: white's where it says `light`, else black's --
    another word, or a file that is not there or does not read."""
    try:
        with open(path, encoding="utf-8") as file:
            return WHITE if file.read().strip() == "light" else BLACK
    except (OSError, ValueError):       # ValueError: bytes that are no UTF-8
        return BLACK


if __name__ == "__main__":
    print(*(ROLES[role][fits(sys.argv[1])] for role in sys.argv[2:]))
