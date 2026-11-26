"""What a point of a model's own cap takes from its login's shared week: it hides how the share is
read off the kept readings.

A probe reads a login's shared week and its scoped cap together, both in whole points, so each end
of a stretch between two readings is off by up to half a point.  Across any two readings of one
login on a plan with no reading between them where either meter fell, a cap rise `f` above 1 beside
a week rise `a` bounds the share from above by `(a + 1) / (f - 1)`: any other model that ran only
added to `a`, and rounding can only raise the ceiling.  The least ceiling over every stretch of
every login on the plan is the share.
"""

from contextlib import closing
import math
import sqlite3

from . import config, history, usage, week_meters


def of(provider, plan, scope):
    """The share of its login's shared week a point of `scope`'s cap takes on `provider`'s `plan`,
    or None where no kept stretch of that plan has the cap rising above 1 or the history cannot
    answer.

    Reads history.db once, read-only, in one snapshot: no migration runs ahead of it.  Each
    login's shared week is what `week_meters.shared_weeks` names for it, and only moments holding
    both that meter (no `scope`) and `scope`'s cap on `plan`, with valid numeric `used` and `at`,
    are readings.  Readings where neither meter moved are dropped before pairing stretches.
    """
    if not (usage._text(provider) and usage._text(plan) and usage._text(scope)):
        return None
    try:
        cfg = config.load()
        with closing(history._connect(readonly=True)) as db:
            db.execute("BEGIN")     # one snapshot for the reads; in WAL no write waits
            weeks = {account: meter
                     for prov, account, meter in week_meters.shared_weeks(
                         cfg, -math.inf, math.inf, db=db)
                     if prov == provider}
            if not weeks:
                return None
            rows = db.execute(
                "SELECT account, meter, used, at, scope FROM meter_readings "
                "WHERE provider = ? AND plan = ? AND source = 'probe' "
                "AND (scope IS NULL OR scope = ?) "
                "AND typeof(used) IN ('integer', 'real') AND used >= 0 AND used <= 100 "
                "AND typeof(at) IN ('integer', 'real') "
                "ORDER BY at, rowid",
                (provider, plan, scope)).fetchall()
    except (config.Error, OSError, sqlite3.Error):
        return None
    by_login = {}       # {account: {at: [week_used, cap_used]}}
    for account, meter, used, at, row_scope in rows:
        if not math.isfinite(at) or (week := weeks.get(account)) is None:
            continue
        if row_scope is None:
            if meter != week:
                continue
            slot = 0
        else:
            slot = 1
        by_login.setdefault(account, {}).setdefault(at, [None, None])[slot] = used
    return _share(
        [(week, cap) for week, cap in moments.values() if week is not None and cap is not None]
        for moments in by_login.values())


def _share(logins):
    """The least `(a + 1) / (f - 1)` over every stretch of every login's readings whose cap rose
    above 1, or None where none did.

    A reading where neither meter moved is dropped first: it adds no new stretch and keeps the
    pair count bounded by the distinct meter positions in a run.  A reading where either meter fell
    ends the run before it and starts a new one.
    """
    best = None
    for readings in logins:
        run = []
        for week, cap in readings:
            if run:
                prev_w, prev_c = run[-1]
                if week == prev_w and cap == prev_c:
                    continue
                if week < prev_w or cap < prev_c:
                    run = [(week, cap)]
                    continue
                for start_w, start_c in run:
                    cap_rise = cap - start_c
                    if cap_rise > 1:
                        ceiling = (week - start_w + 1) / (cap_rise - 1)
                        if best is None or ceiling < best:
                            best = ceiling
            run.append((week, cap))
    return best
