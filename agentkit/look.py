"""A pass's one look at what its readers share, however many of them ask."""

import threading
import time
from contextlib import contextmanager

_FOUND = threading.local()      # what this thread's pass has found so far, by what was asked
_HELD = {}                      # what any pass of this process computed: {key: (good until, it)}
_HOLDING = threading.Lock()     # around computing, so two threads asking at once ask once


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


@contextmanager
def aside():
    """Out of this thread's pass meanwhile: a writer under a lock decides on the disk as it is."""
    found = getattr(_FOUND, "by", None)
    if found is None:
        yield
        return
    del _FOUND.by
    try:
        yield
    finally:
        _FOUND.by = found


def once(key, compute):
    """`compute()`; in a pass, what its first ask for `key` on this thread computed, so only
    read."""
    found = getattr(_FOUND, "by", None)
    if found is None:
        return compute()
    if key not in found:
        found[key] = compute()
    return found[key]


def held(key, every, compute):
    """`compute()`; in a pass, what any pass in this process computed for `key` less than `every`
    seconds before it asked, so a wrong answer lasts that long at most and nothing invalidates
    it.  `compute` asks nothing held.  Outside a pass nothing is kept."""
    if not hasattr(_FOUND, "by"):
        return compute()
    with _HOLDING:
        now = time.monotonic()
        if _HELD.get(key, (now,))[0] <= now:
            for gone in [old for old, (until, _) in _HELD.items() if until <= now]:
                del _HELD[gone]      # on a screen open for days, a checkout long gone
            _HELD[key] = (now + every, compute())
        return _HELD[key][1]
