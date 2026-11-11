"""The owner's palette (10 Nov 2026): every colour ak draws, each with the text that reads on it.

The eight and the grey kept from before; text of no colour is the terminal's own.  A role names a
colour of it (`terminal.STATE_STYLES`), and tests/test_boundaries.py counts an RGB written
anywhere but here, so the next palette is this table.
"""

from collections import namedtuple

Colour = namedtuple("Colour", "rgb ink")
PALETTE = {
    "blue": Colour("0067c6", "ffffff"),
    "red": Colour("be222a", "ffffff"),
    "orange": Colour("de6800", "2e1500"),
    "yellow": Colour("f6c400", "3d2e00"),
    "green": Colour("007e46", "ffffff"),
    "teal": Colour("007974", "ffffff"),
    "purple": Colour("7c44c3", "ffffff"),
    "pink": Colour("ad326e", "ffffff"),
    "grey": Colour("6c7086", "ffffff"),
}
