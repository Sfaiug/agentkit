"""The owner's two themes (12 Nov 2026), white and black: every colour ak draws is a role of one.

A screen asks for a role, and the theme in force (`terminal.theme`) says its colour: the one
config.toml names (`named`), else the one the terminal's background fits.
tests/test_boundaries.py counts an RGB written anywhere but here, so the next theme is a column
of this table.  Run bare, `themes.py <config.toml> <role>`, it says the role's colour as tmux
draws it (`terminal.colour`'s `tmux`): `Ctrl-b m`'s job asks it as the key is pressed
(orch.FLOAT), and a start of Python that imports no more than this holds the popup up least.
"""

import sys
import tomllib

WHITE, BLACK = 0, 1     # each theme's column
NAMES = {"black": BLACK, "white": WHITE}    # ... by its name, as config.toml and `c` say it
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


def named(path):
    """The theme config.toml at `path` names, `theme = "white"` or `"black"`, else None: another
    word, or a file that is not there or does not read."""
    try:
        with open(path, "rb") as file:
            word = tomllib.load(file).get("theme")
    except (OSError, ValueError):     # a TOMLDecodeError and a UnicodeDecodeError are ValueErrors
        return None
    return NAMES.get(word) if isinstance(word, str) else None


if __name__ == "__main__":
    chosen = named(sys.argv[1])
    print(ROLES[sys.argv[2]][BLACK if chosen is None else chosen])
