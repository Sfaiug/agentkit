"""A pass's one look at what its readers share, however many of them ask."""

import threading
from contextlib import contextmanager

_FOUND = threading.local()      # what this thread's pass has found so far, by what was asked


@contextmanager
def one_look():
    """A pass: every ask on its thread gets what the first found (`once`), and the next pass
    looks again.  One opened inside it is part of it; another thread looks for itself."""
    if hasattr(_FOUND, "by"):
        yield
        return
    _FOUND.by = {}
    try:
        yield
    finally:
        del _FOUND.by


def once(key, compute):
    """`compute()`; in a pass, what its first ask for `key` on this thread computed, so only
    read."""
    found = getattr(_FOUND, "by", None)
    if found is None:
        return compute()
    if key not in found:
        found[key] = compute()
    return found[key]
