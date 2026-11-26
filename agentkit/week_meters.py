"""What each plan's weekly meters rose, and the tokens that ran meanwhile, a day at a time (`days`),
and what each run's builds and reviews took of them (`run_usage`): it hides how readings and
tokens are paired.  A step is two probe readings of a login's shared week next to each other in
time, holding the tokens the login ran on its provider's harnesses after the first and by the
second, so nothing between two readings is kept, cut or carried.  A token costs no price here: a
meter is what a plan gives, and a listed dollar is not what it takes.  `ak models --json` sums the
days into `week_meters`, fits each model's rate from them, and values every run's turns at those
rates.
"""

from bisect import bisect_right
from contextlib import closing
from fractions import Fraction
import sqlite3

from . import config, history, rates, spend, staffing, usage

DAY = 86400


def days(cfg, since, until, *, meters=None):
    """[(provider, plan, points, {model: tokens})] of each login, plan and day (the whole days
    since 1970 in UTC of a step's second reading) between `since` and `until` with a step that
    counts: the points its steps rose, exactly, so that days summed and rounded once are what
    `math.fsum` makes of their steps, and each model's tokens in them.

    A login's readings are its probe readings of its shared week (`shared_weeks`), a model's
    own cap of that name (`scope`) none, whose `used` is a number from 0 to 100 and whose `at` is
    a number, in the order of `at`, then of the row; any other row is no reading.  A step is two
    of a login's readings next to each other: it counts where both name one plan (`usage._text`)
    and the second holds no less than the first, rising by the difference, as a step across two
    plans, from or to a reading naming none, or
    down (a week that began again) says nothing of what its tokens took.  It holds the login's
    rows of its provider's harnesses (`spend._ours`) after its first reading and by its second:
    a seat row its `tokens`, a turn row its four counts summed, each a whole number or a turn
    row's NULL, summing above zero, any other row no row; one holding a row of no model counts
    for nothing, as what that row ran is unknown.  Read in one transaction of the history, so a
    row written meanwhile is in all reads or none; none where it cannot answer, as one
    whose readings keep no plan, no write having migrated it since."""
    ours = _ours(cfg)
    history._ensure_migrated()      # a meter_readings table from before plan and scope has neither
    try:
        with closing(history._connect(readonly=True)) as db:
            db.execute("BEGIN")     # one snapshot for the reads; in WAL no write waits
            active = shared_weeks(cfg, since, until, db=db) if meters is None else meters
            logins = _readings(db, active, since, until)
            # seat_tokens creates `seat_usage` separately; absent means no seat rows yet
            seats = (db.execute("SELECT account, event, model, at, tokens FROM seat_usage "
                                "WHERE at > ? AND at <= ?", (since, until)).fetchall()
                     if db.execute("SELECT 1 FROM pragma_table_info('seat_usage')").fetchone()
                     else [])
            turns = db.execute("SELECT account, turn, model, at, input, cache_write, cache_read, "
                               "output FROM turn_usage WHERE at > ? AND at <= ?",
                               (since, until)).fetchall()
    except (OSError, sqlite3.Error):
        return []
    ran = {}        # {(provider, account): [(at, model, tokens)]}
    for account, event, model, at, tokens in seats:
        if type(tokens) is int and tokens > 0:
            ran_on = event.split(":", 1)[0] if isinstance(event, str) else None
            for provider, match in ours.items():
                if match(ran_on):
                    ran.setdefault((provider, account), []).append((at, usage._text(model), tokens))
    for account, turn, model, at, *counts in turns:
        if (found := _turn(ours, turn, counts)) is not None:
            provider, tokens = found
            ran.setdefault((provider, account), []).append((at, usage._text(model), tokens))
    found = {}      # {(provider, account, plan, day): [points, {model: tokens}]}
    for login, readings in logins.items():
        kept = sorted(ran.get(login, []), key=lambda row: row[0])
        times = [at for at, *_ in kept]
        for (began, low, plan), (at, used, then) in zip(readings, readings[1:]):
            step = kept[bisect_right(times, began):bisect_right(times, at)]
            if (plan is None or plan != then or used < low
                    or any(model is None for _, model, _ in step)):
                continue
            day = found.setdefault((*login, plan, int(at // DAY)), [Fraction(0), {}])
            day[0] += Fraction(used - low)
            for _, model, count in step:
                day[1][model] = day[1].get(model, 0) + count
    return [(provider, plan, points, tokens)
            for (provider, _, plan, _), (points, tokens) in found.items()]


def run_usage(cfg, since, until, fitted, *, meters=None):
    """{(run_id, role): ({(provider, plan): points}, unrated)} of the `turn_usage` rows in
    (since, until] naming a run and a role, valued at `fitted`, `rates.fitted`'s exact rates.

    A row is chosen as `days` chooses one (`_turn`), and its plan is the one its login's reading
    (`_readings`) last at or before the row's `at` names, else its first reading after.  Where
    that names a plan with a rate for its model, its tokens take `tokens * rate / MILLION`
    points under `(provider, plan)`, summed exactly (a plan taking none not named); else its
    tokens are `unrated`.  {} where the history cannot answer."""
    ours = _ours(cfg)
    history._ensure_migrated()      # a meter_readings table from before plan and scope has neither
    try:
        with closing(history._connect(readonly=True)) as db:
            db.execute("BEGIN")
            active = shared_weeks(cfg, since, until, db=db) if meters is None else meters
            logins = _readings(db, active, since, until)
            turns = db.execute(
                "SELECT run_id, role, account, turn, model, at, input, cache_write, cache_read, "
                "output FROM turn_usage WHERE at > ? AND at <= ?", (since, until)).fetchall()
    except (OSError, sqlite3.Error):
        return {}
    times = {login: [at for at, *_ in readings] for login, readings in logins.items()}
    used = {}       # {(run_id, role): [{(provider, plan): Fraction}, unrated]}
    for run_id, role, account, turn, model, at, *counts in turns:
        run_id, role = usage._text(run_id), usage._text(role)
        if run_id is None or role is None or (found := _turn(ours, turn, counts)) is None:
            continue
        provider, tokens = found
        readings = logins.get((provider, account))
        plan = (readings[max(0, bisect_right(times[provider, account], at) - 1)][2]
                if readings else None)
        model = usage._text(model)
        rate = (fitted.get((provider, plan), {}).get(model)
                if plan is not None and model is not None else None)
        points, unrated = used.setdefault((run_id, role), [{}, 0])
        if rate is None:
            used[run_id, role][1] = unrated + tokens
        elif rate:
            points[provider, plan] = (points.get((provider, plan), Fraction(0))
                                      + tokens * rate / rates.MILLION)
    return {key: (points, unrated) for key, (points, unrated) in used.items()}


def shared_weeks(cfg, since, until, *, db=None):
    """{(provider, account, meter)} of each configured provider's logins' shared week now
    (`usage.week_names`), read once so `days` and `run_usage` select the same readings.  A login
    a configured provider no longer lists that has probe readings in [since, until] takes the
    one shared week its configured logins name between them; a provider whose configured logins
    name two or none gains no login."""
    configured = {name: set(config.accounts(cfg, name) or [config.DEFAULT_ACCOUNT])
                  for name in cfg["providers"]}
    held = {name: prov for name, prov in staffing._cached_providers().items()
            if name in configured}
    known = {(provider, login, meter)
             for provider, accounts in usage.week_names(cfg, held).items()
             for account, meter in accounts.items()
             if meter is not None
             and (login := account or config.DEFAULT_ACCOUNT) in configured[provider]}
    by_provider = {}
    for provider, _, meter in known:
        by_provider.setdefault(provider, set()).add(meter)
    one = {provider: next(iter(found)) for provider, found in by_provider.items()
           if len(found) == 1}
    if not one:
        return known
    return known | {(provider, account, one[provider])
                    for provider, account in _probe_logins(db, since, until)
                    if provider in one and usage._text(account) is not None
                    and account not in configured[provider]}


def _probe_logins(db, since, until):
    """[(provider, account)] with probe readings in [since, until], using `db` or a fresh
    read-only connection; [] where the history cannot be read."""
    query = ("SELECT DISTINCT provider, account FROM meter_readings "
             "WHERE source = 'probe' AND typeof(at) IN ('integer', 'real') "
             "AND at >= ? AND at <= ?")
    if db is not None:
        return db.execute(query, (since, until)).fetchall()
    try:
        with closing(history._connect(readonly=True)) as conn:
            return conn.execute(query, (since, until)).fetchall()
    except (OSError, sqlite3.Error):
        return []


def _ours(cfg):
    """{provider: harness match (`spend._ours`)} of every configured provider."""
    return {provider: spend._ours(cfg, provider) for provider in cfg["providers"]}


def _readings(db, meters, since, until):
    """{(provider, account): [(at, used, plan)] in order} of each login's probe readings of its
    shared week in [since, until] (`meters`), a model's own cap none."""
    # a history no write has added `scope` to yet names no model's own cap
    scope = "scope" if db.execute("SELECT 1 FROM pragma_table_info('meter_readings') "
                                  "WHERE name = 'scope'").fetchone() else "NULL"
    rows = db.execute(
        "SELECT provider, account, meter, at, used, plan FROM meter_readings "
        f"WHERE source = 'probe' AND {scope} IS NULL AND typeof(used) IN "
        "('integer', 'real') AND used >= 0 AND used <= 100 AND typeof(at) IN "
        "('integer', 'real') AND at >= ? AND at <= ? ORDER BY at, rowid",
        (since, until)).fetchall()
    logins = {}
    for provider, account, meter, at, used, plan in rows:
        if (provider, account, meter) in meters:
            logins.setdefault((provider, account), []).append((at, used, usage._text(plan)))
    return logins


def _turn(ours, turn, counts):
    """(provider, tokens) of a `turn_usage` row `days` counts tokens from, None for any other:
    its four counts whole numbers (or NULL) summing above zero, on a harness of that provider."""
    if not all(count is None or type(count) is int for count in counts):
        return None
    tokens = sum(count or 0 for count in counts)
    if tokens <= 0:
        return None
    try:
        ran_on = spend._harness(turn) if isinstance(turn, str) else None
    except ValueError:      # bytes no text decodes, or a NUL in its name
        return None
    provider = next((name for name, match in ours.items() if match(ran_on)), None)
    return (provider, tokens) if provider is not None else None
