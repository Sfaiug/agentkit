"""The owner (20 Nov 2026): "I dont like that the user can switch and choose. First off I dont want
2 themes, I just want one, and the background of the terminal which the user has in its setting
should be used, and ak just sits on top of that."  On a light terminal: "Adapt by itself".

So nothing chooses: a screen asks for a role, and the theme in force (`terminal.theme`) says its
colour, white's or black's: the one the terminal's background fits (`theme_of`), else the one a
menu's answer last kept fits (`fits`), black where none is.  tests/test_boundaries.py counts an
RGB written anywhere but here.  Run bare, `themes.py <config.toml> <role>...`, it says each role's
colour as tmux draws it (`terminal.colour`'s `tmux`), in the theme kept in the state beside it, on
one line; `themes.py <config.toml> look <role>...` says them in the look on the colour kept, where
the look reads there (reads.look), that colour after them, else as the first form does:
`Ctrl-b m`'s job asks that as the key is pressed (orch.FLOAT), and one start of Python that imports
no more than this, and reads only where a colour is kept, holds the popup up least.
"""

import os
import sys

WHITE, BLACK = 0, 1     # each theme's column
KEPT = "background"     # the file in ak's state the last answer is kept in (`terminal._keep`)
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


def said(path):
    """The words of the answer kept at `path`: `light` or `dark`, then the colour it named
    (`terminal._keep`), the colour none where a release before this kept the word alone."""
    try:
        with open(path, encoding="utf-8") as file:
            return file.read().split()
    except (OSError, ValueError):       # ValueError: bytes that are no UTF-8
        return []


def fits(words):
    """The theme an answer kept fits, `words` what it says (`said`): white where the first is
    `light`, else black."""
    return WHITE if words[:1] == ["light"] else BLACK


def theme_of(red, green, blue):
    """The theme a background fits whose channels, each from 0 to 1, are these: white where its
    luma is past half way, else black."""
    return WHITE if 0.2126 * red + 0.7152 * green + 0.0722 * blue > 0.5 else BLACK


def theme_of_rgb(rgb):
    """The theme a background of `rgb`, rrggbb, fits (`theme_of`), None where `rgb` is no such
    colour."""
    try:
        red, green, blue = bytes.fromhex(rgb) if len(rgb) == 6 else b""
    except ValueError:
        return None
    return theme_of(red / 255, green / 255, blue / 255)


if __name__ == "__main__":
    path, roles = os.path.join(os.path.dirname(sys.argv[1]), "state", KEPT), sys.argv[2:]  # STATE
    words, look = said(path), None      # read once: what is said is all of one answer
    if roles[:1] == ["look"]:
        roles, colour = roles[1:], "".join(words[1:2])
        # only a colour the menu handed it takes in the theme kept (terminal.sense), which its
        # rounding to rrggbb can tip at half way; what reads imports, only then
        if theme_of_rgb(colour) == fits(words):
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from agentkit import reads
            look = reads.look(colour, fits(words))
    if look:
        print(*(look[role] for role in roles), colour)
    else:
        print(*(ROLES[role][fits(words)] for role in roles))
