"""The owner's two themes (12 Nov 2026), white and black: every colour ak draws is a role of one.

A screen asks for a role, and the theme in force (`terminal.THEME`, set where the background is
read) says its colour.  tests/test_boundaries.py counts an RGB written anywhere but here, so the
next theme is a column of this table.
"""

WHITE, BLACK = 0, 1     # each theme's column
ROLES = {
    #              white     black
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
