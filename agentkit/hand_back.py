"""`ak standby --steady`: whether this machine, a home's client, is steady enough to be given home
back by the machine that stood in for it.  This hides what steady means, and the half hour.

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

from . import config, lease, pair_clock, pause, standby

STEADY = 30 * 60    # seconds up: a floor, as a machine up longer is as steady


def steady():
    """Whether this machine is steady: no for whatever is raised."""
    try:
        alias, now = config.server_alias(), pair_clock.now()
        stamp = alias and standby._copied(alias)[0]
        return bool(stamp) and stamp.boot == now.boot and now.since >= STEADY \
            and stamp.age_at_most() < pause.STALE and lease.watching()
    except Exception:
        return False
