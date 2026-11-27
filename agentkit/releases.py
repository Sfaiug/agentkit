"""Which of a harness's listed models are the newest release of their line.

How a label gives a line and a release stays here: a label's first number (digits, and more
digits after each `.`) is its release, compared part by part as whole numbers with a missing part
below any; the rest of the label, lower case with every run of other than letters and digits one
space, is its line.  `Bolt 5.5`, `Bolt 5` and `Bolt 4.8` are one line; `Bolt 5.5` and
`Bolt 5.5 Fast` are two; a label with no number is a line of its own.
"""

import re

NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)*")


def _line_release(label):
    """`(line, release)` of `label`, or None where it holds no number."""
    found = NUMBER.search(label)
    if not found:
        return None
    rest = label[:found.start()] + " " + label[found.end():]
    line = " ".join("".join(char if char.isalnum() else " " for char in rest.lower()).split())
    return line, tuple(int(part) for part in found.group(0).split("."))


def newest(models):
    """The models of `models` (each holding `label`) where no other of the same line has a higher
    release, in `models`'s order.  A model whose label holds no number is always kept."""
    parsed = [_line_release(model["label"]) for model in models]
    best = {}
    for entry in parsed:
        if entry is not None:
            line, release = entry
            if line not in best or release > best[line]:
                best[line] = release
    return [model for model, entry in zip(models, parsed)
            if entry is None or entry[1] == best[entry[0]]]
