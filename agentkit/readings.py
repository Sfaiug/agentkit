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

import bisect
from collections import namedtuple
from contextlib import suppress
import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
import math
import os
import socket
import stat
import time

from . import config, history

HOUR = 3600
_US = 1_000_000
_HOUR_US = HOUR * _US
PROCESSORS_SHORT = 1       # above 1, work stood in line for a processor
# a tenth or more: on 25 Nov 2026 the busiest home's hours all read 0, and anything near a tenth
# is an hour a person would have felt
MEMORY_WAIT_SHORT = Fraction(1, 10)


class Hour(namedtuple("Hour", "start processors memory memory_wait short_of")):
    """One hour's readings, starting at `start` (inclusive) for 3600 seconds: `processors` is
    the mean of `load / cores`, `memory` the mean share of `memory_mb` in use, `memory_wait`
    the share of the hour work stood waiting for memory from rises of `memory_stall_us` between
    readings, each None where the hour has no usable reading (or, for `memory_wait`, no step
    carrying the counter), and `short_of` is `("processors",)`, `("memory",)`, both, or `()`."""


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
    """The `count` hours ending at `until`, oldest first, for `name`: this host's `home` lines
    when `home` is true, or a listed machine's `machine` lines when false.

    Each entry is an `Hour` covering `[start, start + 3600)`.  Reads every day file in the
    readings folder and places each usable line by its own `at`, computing no calendar date.
    """
    edges = [until - (count - i) * HOUR for i in range(count + 1)]
    folder = config.STATE / "readings"
    try:
        files = sorted(entry for entry in os.listdir(folder) if _day(entry) is not None)
    except OSError:
        files = []

    key, other = ("home", "machine") if home else ("machine", "home")
    seen = [0] * count
    # exact rational sums avoid both float overflow near float max and rounding past 1 at exact 1
    processors = [Fraction(0)] * count
    memory = [Fraction(0)] * count
    before = None   # latest usable reading before edges[0]: (at, stall)
    ordered = []    # (at, stall, index) for every usable reading inside the window
    for entry in files:
        with suppress(OSError):
            # open closes an opener's descriptor it refuses (a directory); nonblocking skips a FIFO
            with open(folder / entry, "rb",
                      opener=lambda path, flags: os.open(path, flags | os.O_NONBLOCK)) as file:
                if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                    continue
                for raw in file:
                    reading = _usable(raw, key, other, name)
                    if reading is None:
                        continue
                    at, load, cores, memory_mb, free_mb, stall = reading
                    # against the very edges the hours start at, so no rounding moves a line
                    index = bisect.bisect_right(edges, at) - 1
                    if not 0 <= index < count:
                        if at < edges[0] and (before is None or at >= before[0]):
                            before = (at, stall)
                        continue
                    seen[index] += 1
                    processors[index] += Fraction(load) / Fraction(cores)
                    memory[index] += (Fraction(memory_mb) - Fraction(free_mb)) / Fraction(memory_mb)
                    ordered.append((at, stall, index))
    wait_us = [None] * count
    ordered.sort(key=lambda item: item[0])
    prev = before
    for at, stall, index in ordered:
        if prev is not None and stall is not None and prev[1] is not None:
            prev_at, prev_stall = prev
            if wait_us[index] is None:
                wait_us[index] = Fraction(0)
            if stall > prev_stall:
                delta = stall - prev_stall
                dt = Fraction(at) - Fraction(prev_at)
                # cap at dt and at one hour; checking dt >= HOUR first keeps large intervals tiny
                limit = _HOUR_US if dt >= HOUR else dt * _US
                wait_us[index] += delta if delta <= limit else limit
        prev = (at, stall)
    return [_hour(edges[i], seen[i], processors[i], memory[i], wait_us[i]) for i in range(count)]


def _hour(start, count, proc_sum, mem_sum, wait_us):
    """Build one `Hour`, judging shortages on the exact rational means before converting to float."""
    if not count:
        return Hour(start, None, None, None, ())
    proc = proc_sum / count
    wait = None if wait_us is None else min(wait_us, _HOUR_US) / Fraction(_HOUR_US)
    short = (*(("processors",) if proc > PROCESSORS_SHORT else ()),
             *(("memory",) if wait is not None and wait >= MEMORY_WAIT_SHORT else ()))
    return Hour(start, float(proc), float(mem_sum / count),
                None if wait is None else float(wait), short)


def _usable(raw, key, other, name):
    """`(at, load, cores, memory_mb, free_mb, memory_stall_us)` for a usable line matching `key`
    == `name` without `other`, else None.  `memory_stall_us` is a whole number of 0 or more, or
    None when absent or anything else."""
    try:
        # parse_float=Decimal keeps stored decimals exact (e.g. 3.6 and 4.4 average to exact 4)
        line = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, ValueError, RecursionError, InvalidOperation):
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
    stall = line.get("memory_stall_us")
    stall = stall if type(stall) is int and stall >= 0 else None
    return at, load, cores, memory_mb, free_mb, stall


def _finite(value):
    """`value` when it is a finite JSON number (never a bool, never overflowing float), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    if not math.isfinite(number):
        return None
    # a decimal tiny enough to underflow float (e.g. 1e-999999999) would explode Fraction's denominator
    if isinstance(value, Decimal) and number == 0.0:
        return 0 if value >= 0 else None
    return value


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
