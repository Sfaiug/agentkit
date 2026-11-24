"""The owner (20 Nov 2026): "I dont like that the user can switch and choose. First off I dont want
2 themes, I just want one, and the background of the terminal which the user has in its setting
should be used, and ak just sits on top of that."  On a light terminal: "Adapt by itself".

So nothing chooses: a screen asks for a role, and the theme in force (`terminal.theme`) says its
colour, white's or black's: the one the terminal's background fits, else the one a menu's answer
last kept fits (`fits`), black where none is.  tests/test_boundaries.py counts an RGB written
anywhere but here.  Run bare, `themes.py <config.toml> <role>...`, it says each role's colour as
tmux draws it (`terminal.colour`'s `tmux`), in the theme kept in the state beside it, on one
line: `Ctrl-b m`'s job asks them as the key is pressed (orch.FLOAT), and one start of Python that
imports no more than this holds the popup up least.
"""

import os
import sys

WHITE, BLACK = 0, 1     # each theme's column
KEPT = "background"     # the file in ak's state the last answer is kept in: `light`, else dark
ROLES = {
    "background": ("ffffff", "000000"),
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
# that say where a thing stands in the spectrum's order, each theme's own rainbow (motion.lit).
RAINBOW = ("error", "warning", "success", "info", "accent", "special")


def fits(path):
    """The theme the answer kept at `path` fits: white where it says `light`, else black."""
    try:
        with open(path, encoding="utf-8") as file:
            return WHITE if file.read().strip() == "light" else BLACK
    except (OSError, ValueError):       # ValueError: bytes that are no UTF-8
        return BLACK


if __name__ == "__main__":
    kept = fits(os.path.join(os.path.dirname(sys.argv[1]), "state", KEPT))     # config.STATE
    print(*(ROLES[role][kept] for role in sys.argv[2:]))
