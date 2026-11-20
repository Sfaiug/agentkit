"""A home a machine takes over from stands still once its proof that it is the home is `STALE`
old, so a standby that takes a lease standing still longer finds it doing nothing.  This hides the
10 minutes, that the proof is read from the lease's repository (`lease.proof_age`), and the
freezer's file: `cgroup.freeze` of ak's slice, where seats, runs, landers and checks run.

Standing still is that slice frozen, which loses nothing: a thaw carries on where it stood.  The
tick is cron's and runs outside the slice, as does whatever else ak started outside it.  Nothing
else of ak freezes the slice, so a home that is not paused thaws it whoever froze it, and no state
is kept.
"""

import os

from . import lease, orch, standby

# A home's tick fires every three minutes, so three more turns were tried before it pauses; a
# standby waits twice this.
STALE = 10 * 60


def paused():
    """Whether this firing ends here: where a record says a machine takes over from this one and
    the proof is `STALE` old, the slice is frozen and it does; else the slice is thawed where it
    is frozen.  A freezer's file that is not there is not made, and one that cannot be read or
    written is left."""
    age = lease.proof_age() if standby.takes_over() else None
    stale = age is not None and age >= STALE
    try:
        freezer = orch.slice_cgroup() / "cgroup.freeze"
        if stale or freezer.read_text().strip() == "1":
            # as `echo 1 >` writes it, but never creating it
            with open(os.open(freezer, os.O_WRONLY | os.O_TRUNC), "w") as file:
                file.write("1" if stale else "0")
    except (OSError, ValueError):
        pass
    return stale
