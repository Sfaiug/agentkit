"""What each machine answered, check by check, for its owner to judge it by over time.  The
format, which nothing else in ak knows:

- A day's file is readings/YYYY-MM-DD.jsonl under ak's state folder, named by the UTC date of
  the check's time.
- A check appends to it in one os.write: a newline, then one line per reading, each ended by a
  newline.  The leading newline ends whatever an interrupted write left before it, so an empty
  line means nothing.  A check with no reading to write opens no file.
- A line is a JSON object: `at`, the check's time; then `home`, this host's name, for this
  machine, or `machine`, the name it was added under, for any other, so the two are never
  taken for each other; then the reading as machines.json takes it.  A reading JSON cannot hold
  (`allow_nan=False`) is left out.
- After its write, a check unlinks each file named a date `datetime.date.fromisoformat` reads
  and `.jsonl`, of a day before the check's less history.READINGS_KEPT_FOR; no other name.

What the disk refuses is skipped on writes and reads alike: a check goes on, and an unreadable
file or unusable line is left out.
"""

from collections import namedtuple
from contextlib import suppress
import datetime
import json
import math
import os
import socket
import time

from . import config, history

HOUR = 3600


class Hour(namedtuple("Hour", "start processors memory")):
    """One hour's means, starting at `start` (whole seconds, inclusive) for 3600 seconds:
    `processors` is the mean of `load / cores`, `memory` the mean share of `memory_mb` in use,
    or both None where the hour has no usable reading."""


def keep(at, said):
    """Append the readings of `said`, each machine's name to what it answered, checked at `at`."""
    from .machines import HERE      # here, not at the top: machines calls this module
    lines = []
    for name, reading in said.items():
        # OSError: no name for this host; ValueError: a number JSON has no word for, nan or inf
        with suppress(OSError, ValueError):
            who = {"home": socket.gethostname()} if name == HERE else {"machine": name}
            lines.append(json.dumps({"at": at, **who, **reading}, allow_nan=False) + "\n")
    if not lines:
        return
    folder = config.STATE / "readings"
    with suppress(OSError):
        folder.mkdir(exist_ok=True)
        day = os.open(folder / f"{_date(at)}.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(day, "".join(["\n", *lines]).encode())
        finally:
            os.close(day)
        gone = _date(at - history.READINGS_KEPT_FOR)
        for entry in os.listdir(folder):
            found = _day(entry)
            if found is not None and found < gone:
                with suppress(OSError):
                    os.unlink(folder / entry)


def hours(name, until, count, *, home):
    """The `count` hours ending at `until` (whole seconds), oldest first, for `name`: this
    host's `home` lines when `home` is true, or a listed machine's `machine` lines when false.

    Each entry is an `Hour` covering `[start, start + 3600)` in whole seconds from `until`.
    Reads every day file in the readings folder and places each usable line by its own `at`,
    computing no calendar date.
    """
    start = until - count * HOUR
    if not count or until <= 0:
        return [Hour(start + i * HOUR, None, None) for i in range(count)]

    folder = config.STATE / "readings"
    try:
        files = sorted(entry for entry in os.listdir(folder) if _day(entry) is not None)
    except OSError:
        files = []

    key, other = ("home", "machine") if home else ("machine", "home")
    seen = [0] * count
    processors = [0.0] * count
    memory = [0.0] * count
    for entry in files:
        with suppress(OSError):
            with open(folder / entry, "rb") as file:
                for raw in file:
                    reading = _usable(raw, key, other, name)
                    if reading is None:
                        continue
                    at, proc, mem = reading
                    # floor(at) is exact for any finite number against integer hour edges
                    second = math.floor(at)
                    if not (start <= second < until):
                        continue
                    index = (second - start) // HOUR
                    seen[index] += 1
                    n = seen[index]
                    # running mean stays finite even when readings are near float max
                    processors[index] += (proc - processors[index]) / n
                    memory[index] += (mem - memory[index]) / n
    return [Hour(start + i * HOUR, processors[i], memory[i]) if seen[i]
            else Hour(start + i * HOUR, None, None) for i in range(count)]


def _usable(raw, key, other, name):
    """`(at, load / cores, (memory_mb - free_mb) / memory_mb)` for a usable line matching `key`
    == `name` without `other`, else None."""
    try:
        line = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(line, dict) or line.get(key) != name or other in line:
        return None
    at = _finite(line.get("at"))
    load = _finite(line.get("load"))
    cores = _finite(line.get("cores"))
    memory_mb = _finite(line.get("memory_mb"))
    free_mb = _finite(line.get("free_mb"))
    if (at is None or load is None or cores is None or memory_mb is None or free_mb is None
            or at < 0 or load < 0 or cores < 1 or memory_mb < 1
            or not (0 <= free_mb <= memory_mb)):
        return None
    return at, load / cores, (memory_mb - free_mb) / memory_mb


def _finite(value):
    """`value` when it is a finite JSON number (never a bool, never overflowing float), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(number) else None


def _day(name):
    """The date a day file is named for, or None for any other name."""
    if not name.endswith(".jsonl"):
        return None
    with suppress(ValueError):
        return datetime.date.fromisoformat(name.removesuffix(".jsonl"))
    return None


def _date(at):
    # gmtime drops the fraction of a second, which datetime would round into the next day
    return datetime.date(*time.gmtime(at)[:3])
