"""`ak standby --steady`: whether this machine, a home's client, is steady enough to be given home
back by the machine that stood in for it; and, on that machine, whether one it gives home back to
says so (`due`).  This hides what steady means, the half hour, and who is asked and how long.

Steady is all of these, read here and never asked of another machine or the remote:
- this machine is a home's client, whichever home its record of a server names;
- it has been up STEADY by the clock since boot, so one back from a power cut has stayed up;
- its last pass from its home that ended well began on this boot, younger than `pause.STALE` by
  the clock calling it older: it carries on from that copy, whole and young;
- it only watches the lease (`lease.watching`).  It keeps no value it made: one given home sends a
  swap keeping the value it sent, so where the remote did not take it, this machine is never steady
  again and home is tried back once, not again and again.  And its watch holds a record of the
  lease made on this boot: one that cannot read the lease would never take it.
"""

import contextlib
import subprocess

from . import config, lease, pair_clock, pause, standby

STEADY = 30 * 60    # seconds up: a floor, as a machine up longer is as steady
# seconds a machine has to say it is steady: a ceiling, as one slower is taken as not steady this
# firing, and each such machine holds the firing up this long
ASKED = 10


def steady():
    """Whether this machine is steady: no for whatever is raised."""
    try:
        alias, now = config.server_alias(), pair_clock.now()
        stamp = alias and standby._copied(alias)[0]
        return bool(stamp) and stamp.boot == now.boot and now.since >= STEADY \
            and stamp.age_at_most() < pause.STALE and lease.watching()
    except Exception:
        return False


def due():
    """Whether home goes back now: asked in the order of their names, by `ak standby --steady`
    there, a machine a record here that reads as a stamp says home goes back to (`back`) says it is
    steady within ASKED.  No where none does, so where no record says `back`, nobody asked."""
    for path in sorted(standby._records()):
        # whatever is raised is no, and the next such machine is asked
        with contextlib.suppress(Exception):
            if standby._record(path)[1] == "back" and subprocess.run(
                    standby._home(path.name, "--steady"), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=ASKED).returncode == 0:
                return True
    return False
