"""A file parsed again only once stat says it changed: its device, inode, mtime, ctime or size.

ak writes its state files whole, so a file whose stat reads as it did when it was parsed still
holds what was parsed from it, and a screen open all day reads only the files that moved.  A file
changed within the second before it is read is read again next time: a filesystem's clock can
give two writes in one tick the same times.  A directory is a file too, its listing its parse.
What comes back is every caller's: read it, never change it in place.
"""

import os
import time

FRESH = 1_000_000_000      # ns since its last change in which a file vouches for no parse
_KEPT = {}                 # (path, parse): (its stat, what parse made of it)


def read(path, parse):
    """`parse(path)` as it was while the file's stat is unchanged.  Raises what stat or `parse`
    raises, FileNotFoundError for no file."""
    key = os.fspath(path), parse
    try:
        info = os.stat(path)
    except OSError:
        _KEPT.pop(key, None)
        raise
    stamp = info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size
    kept = _KEPT.get(key)
    if kept is not None and kept[0] == stamp:
        return kept[1]
    value = parse(path)        # after the stat: a write meanwhile is read again, never missed
    # ctime, which no `touch` sets back, on time_ns, which tests faking time.time leave real
    if time.time_ns() - info.st_ctime_ns >= FRESH:
        _KEPT[key] = stamp, value
    return value


def kept(path, parse):
    """The stat `read` keeps `parse(path)` under and what it made of the file, None for none."""
    return _KEPT.get((os.fspath(path), parse))


def forget(path, parse):
    """Drop what `parse` made of a file gone, which `read` forgets only once asked for it."""
    _KEPT.pop((os.fspath(path), parse), None)


def keep(path, parse, stamp, value):
    """What another process's `kept` said of `parse(path)`, unless this one keeps its own: a
    file whose stat no longer reads `stamp` is parsed again."""
    _KEPT.setdefault((os.fspath(path), parse), (tuple(stamp), value))
