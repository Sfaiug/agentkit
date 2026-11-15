"""How long ago something was, as a pair's home and standby read it: on two clocks, since either
can be wrong.

The wall clock steps, either way.  The clock since boot (CLOCK_BOOTTIME) never steps, but stands
still while the machine is halted whole and begins at nothing at a reboot.  So every time the
pair's code keeps is a `Stamp` of both, and of the boot it was on, and its age is read two ways:
`age_at_most`, which a home asks of its proof that it is still the home, and `age_at_least`,
which a standby asks of its home's silence.  Only the pair's code reads these two clocks; the
rest of ak keeps its own.

The boot is the whole of ak's (`boot`): a process's identity and the tick's reboot are read here.

AK_NOW, a stamp's line, is both clocks and the boot for the one ak it is set for: a key steps one
clock and not the other, or reboots a machine, with it.  Each command's time is then the one its
key set, unmoving.

This module loads nothing else of ak: a timer runs it where bin/ak cannot start.
"""

import math
import os
from pathlib import Path
import time
from typing import NamedTuple

NOW = "AK_NOW"
BOOT = Path("/proc/sys/kernel/random/boot_id")


class Stamp(NamedTuple):
    wall: float     # time.time()
    since: float    # seconds since boot
    boot: str       # the kernel's boot id

    def line(self):
        """The stamp as one line of text, which `read` reads back."""
        return f"{self.wall} {self.since} {self.boot}"

    def age_at_most(self):
        """Seconds since the stamp by whichever clock calls it older.  Across a reboot only the
        wall clock can say; a stamp it then calls later than now is older than any limit."""
        current, wall = self._now()
        if current.boot == self.boot:
            return max(wall, current.since - self.since)
        return wall if wall >= 0 else math.inf

    def age_at_least(self):
        """Seconds since the stamp by whichever clock calls it younger, and never below 0.
        Across a reboot only the wall clock can say."""
        current, wall = self._now()
        if current.boot == self.boot:
            wall = min(wall, current.since - self.since)
        return max(wall, 0)

    def _now(self):
        current = now()
        return current, current.wall - self.wall


def read(line):
    """The stamp a line holds, or None where it holds none."""
    try:
        return _stamp(line)
    except ValueError:
        return None


def _stamp(line):
    wall, since, boot = line.split()
    clocks = float(wall), float(since)
    # A nan or infinite clock makes every age nan or infinite, which no limit can be measured by.
    if not all(map(math.isfinite, clocks)):
        raise ValueError(f"a clock is no time: {line}")
    return Stamp(*clocks, boot)


def now():
    """This machine's stamp now, or the one AK_NOW sets: a key's that cannot be read fails."""
    if NOW in os.environ:
        return _stamp(os.environ[NOW])
    return Stamp(time.time(), time.clock_gettime(time.CLOCK_BOOTTIME), boot())


def boot():
    """The host's boot now, which every restart of it changes, or the one AK_NOW sets; None
    where Linux cannot say."""
    if NOW in os.environ:
        return now().boot
    try:
        return BOOT.read_text().strip()
    except OSError:
        return None
