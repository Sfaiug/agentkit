"""A home runs only while its proof that it is the home is younger than `STALE`, so a standby that
takes a lease standing still longer finds it doing nothing.  One keeping a value it made of the
lease is held to that proof whatever its records say: one that took the lease has no record till a
machine copies it, and one whose standby's ak is older has one saying `no`.  One keeping none is
held to it where a record says a machine takes over from it, and has none: there no proof is no
work, whatever the reason, as each reason told apart is a case to get right: one that lost its
lease's folder reads its own lease as another machine's and writes it no more, so one working on
makes two homes.  This hides the 10 minutes, that the proof is read from the lease's repository
(`lease.proof_age`), and the freezer's file: ak's slice's (`host.freezer`), where seats, runs,
landers and checks run.

Standing still is that slice frozen, which loses nothing: a thaw carries on where it stood.  The
tick is cron's and runs outside the slice, as does whatever else ak started outside it.  Nothing
else of ak freezes the slice, so a home that is not paused thaws it whoever froze it, and no state
is kept.
"""

from . import host, lease, orch, standby

# A home's tick fires every three minutes, so three more turns were tried before it pauses; a
# standby waits twice this.
STALE = 10 * 60


def paused():
    """Whether this firing ends here: where the proof is `STALE` old, or there is none and a record
    says a machine takes over from this one, the slice is frozen and it does; else the slice is
    thawed where it is frozen.  A freezer's file that is not there is not made, and one that
    cannot be read or written is left."""
    age = lease.proof_age()
    # a value kept may be the lease a standby watches, whatever the records say; with none, one
    # nobody takes over from holds no lease, so needs no proof
    stale = standby.takes_over() if age is None else age >= STALE
    try:
        # opened to read and to write, and read before any write, so that one that cannot be
        # either, or a pipe, is left, and none is made; cut to what was written only once that is
        # written, so a write refused leaves what was there
        with open(host.freezer(orch.slice_cgroup()), "r+b") as freezer:
            if freezer.read().strip() == b"1" or stale:
                freezer.seek(0)
                freezer.write(b"1" if stale else b"0")
                freezer.truncate()
    except (OSError, ValueError):     # ValueError: a path no file can have, as one holding a NUL
        pass
    return stale
