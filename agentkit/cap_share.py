"""What a model's own cap takes from its login's shared week (`of`), the most it has been seen to
rise in a span of time (`most`), and the part of that week a cap just read holds for it (`held`):
it hides how all three are read off the kept readings.

For `of`, a reading holds a login's shared week and its scoped cap at one moment, both in whole
points, so each end of a stretch between two readings is off by up to half a point.  Across any
two readings of one login on a plan with no reading between them where either meter fell, a cap
rise `f` above 1 beside a week rise `a` bounds the share from above by `(a + 1) / (f - 1)`: any
other model that ran only added to `a`, and rounding can only raise the ceiling.  The least
ceiling over every stretch of every login on the plan is the share.

For `most`, a reading is one login's kept row of the scoped cap on the plan.  Between two readings
of one login no further apart than `seconds` with no reading between them where the cap fell, the
cap never decreases, so walking each login's readings once finds the largest rise across the plan.
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
    return _read(lambda db: _of(db, provider, plan, scope, _weeks(db, provider)))


def held(provider, plan, account, week, meters, at):
    """`meters`, `account`'s reading of `provider` at `at` on `plan` beside its shared week
    `week`, each model's own cap of them (`scope`) with `held`: the points of that week its share
    (`of`) takes of what it has left, or of the most it has been seen to rise in the time to its
    reset (`most`) where that is less.  Held to the week's last minute, a part its model never
    comes to spend is thrown away: on 7 Nov 2026 a login's week ended with all of Fable's cap
    unspent.  A cap with no share known, or nothing held, is as read, and so is every meter
    where the history cannot answer.

    Reads history.db once, in one snapshot, and not at all for a reading holding no cap.
    `account`'s week is `week` whatever the snapshot of usage holds of it (`shared_weeks`'s
    `newest`): these are that login's newest meters, and the snapshot may hold none of them yet.
    """
    if not usage._text(plan) or not any(usage._text(m.get("scope")) for m in meters):
        return meters

    def hold(db, weeks, cap):
        share = _of(db, provider, plan, cap["scope"], weeks)
        if share is None:
            return cap
        left, resets = 100 - cap["used"], usage._number(cap.get("resets_at"))
        rise = (None if resets is None or resets <= at
                else _rose(db, provider, plan, cap["scope"], resets - at))
        part = share * (left if rise is None else min(left, rise))
        return {**cap, "held": part} if part > 0 else cap

    def reading(db):
        weeks = _weeks(db, provider, (provider, account, week))
        return [hold(db, weeks, m) if usage._text(m.get("scope")) else m for m in meters]
    return _read(reading) or meters


def _read(answer):
    """`answer(db)` over one read-only snapshot of history.db, or None where it or config.toml
    cannot answer: no migration runs ahead of it."""
    try:
        with closing(history._connect(readonly=True)) as db:
            db.execute("BEGIN")     # one snapshot for the reads; in WAL no write waits
            return answer(db)
    except (config.Error, OSError, sqlite3.Error):
        return None


def _weeks(db, provider, newest=None):
    """{account: the name of its shared week} of `provider`'s logins (`shared_weeks`)."""
    return {account: meter for prov, account, meter in week_meters.shared_weeks(
                config.load(), -math.inf, math.inf, db=db, newest=newest) if prov == provider}


def _of(db, provider, plan, scope, weeks):
    """`of` read off `db`, each login's shared week the one `weeks` names for it."""
    if not weeks:
        return None
    rows = db.execute(
        "SELECT account, meter, used, at, scope FROM meter_readings "
        "WHERE provider = ? AND plan = ? "
        "AND (scope IS NULL OR scope = ?) "
        "AND typeof(used) IN ('integer', 'real') AND used >= 0 AND used <= 100 "
        "AND typeof(at) IN ('integer', 'real') "
        "ORDER BY at, rowid",
        (provider, plan, scope)).fetchall()
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


def most(provider, plan, scope, seconds):
    """The largest rise of `scope`'s cap on `provider`'s `plan` between two readings of one login
    no further apart than `seconds`, with no reading between them in which the cap fell, or None
    where no login's kept readings of the cap reach `seconds` apart, no two readings lie within
    `seconds` without a fall, or the history cannot answer.

    Reads history.db once, read-only: no migration runs ahead of it.  A reading is one login's
    row of `meter_readings` for `scope` on `plan` with valid numeric `used` and `at`, in order of
    `at`, walked once.
    """
    if (not (usage._text(provider) and usage._text(plan) and usage._text(scope))
            or isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or (isinstance(seconds, float) and not math.isfinite(seconds)) or seconds <= 0):
        return None
    return _read(lambda db: _rose(db, provider, plan, scope, seconds))


def _rose(db, provider, plan, scope, seconds):
    """`most` read off `db`."""
    rows = db.execute(
        "SELECT account, used, at FROM meter_readings "
        "WHERE provider = ? AND plan = ? AND scope = ? "
        "AND typeof(used) IN ('integer', 'real') AND used >= 0 AND used <= 100 "
        "AND typeof(at) IN ('integer', 'real') "
        "ORDER BY at, rowid",
        (provider, plan, scope)).fetchall()
    by_login = {}       # {account: [(at, cap_used)]}
    for account, used, at in rows:
        if math.isfinite(at) and usage._text(account):
            by_login.setdefault(account, []).append((at, used))
    return _most(by_login.values(), seconds)


def _most(logins, seconds):
    """The largest rise of a cap between two readings of one login no further apart than `seconds`,
    with no reading between them where the cap fell, or None where no login's kept readings reach
    `seconds` apart or no two readings lie within `seconds` without a fall.

    Within a non-falling run the cap never decreases, so the smallest cap inside the `seconds`
    window ending at reading `i` is always at its earliest kept reading `start`.
    """
    best = None
    watched = False
    for readings in logins:
        if len(readings) < 2:
            continue
        if readings[-1][0] - readings[0][0] >= seconds:
            watched = True
        start = 0
        for i, (at, cap) in enumerate(readings):
            if i and cap < readings[i - 1][1]:
                start = i
            while at - readings[start][0] > seconds:
                start += 1
            if start < i:
                rise = cap - readings[start][1]
                if best is None or rise > best:
                    best = rise
    return best if watched else None
