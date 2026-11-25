"""What each plan's weekly meters rose, and the tokens that ran meanwhile, a day at a time: it
hides how readings and tokens are paired.  A step is two probe readings of a login's shared week
next to each other in time, holding the tokens the login ran on its provider's harnesses after
the first and by the second, so nothing between two readings is kept, cut or carried.  A token
costs no price here: a meter is what a plan gives, and a listed dollar is not what it takes.
`ak models --json` sums the days into `week_meters`; the rate a token takes of a week is fitted
from the same days.
"""

from bisect import bisect_right
from contextlib import closing
import math
import sqlite3

from . import config, history, spend, staffing, usage

DAY = 86400


def days(cfg, since, until):
    """[(provider, plan, points, {model: tokens})] of each login, plan and day (the whole days
    since 1970 in UTC of a step's second reading) between `since` and `until` with a step that
    counts: the points its steps rose, summed with `math.fsum`, and each model's tokens in them.

    A login's readings are its probe readings of its shared week (`usage.week_names`) whose
    `used` is a number from 0 to 100 and whose `at` is a number, in the order of `at`, then of
    the row; any other row is no reading.  A step is two of a login's readings next to each
    other: it counts where both name one plan and the second holds no less than the first,
    rising by the difference, as a step across two plans, from or to a reading naming none, or
    down (a week that began again) says nothing of what its tokens took.  It holds the login's
    rows of its provider's harnesses (`spend._ours`) after its first reading and by its second:
    a seat row its `tokens`, a turn row its four counts summed, each a whole number or a turn
    row's NULL, summing above zero, any other row no row; one holding a row of no model counts
    for nothing, as what that row ran is unknown.  Read in one transaction of the history, so a
    row written meanwhile is in all three reads or none; none where it cannot answer, as one
    whose readings keep no plan, no write having migrated it since."""
    held = {name: prov for name, prov in staffing._cached_providers().items()
            if name in cfg["providers"]}
    meters = {(provider, account or config.DEFAULT_ACCOUNT): meter
              for provider, accounts in usage.week_names(cfg, held).items()
              for account, meter in accounts.items() if meter is not None}
    ours = {provider: spend._ours(cfg, provider) for provider, _ in meters}
    try:
        with closing(history._connect(readonly=True)) as db:
            db.execute("BEGIN")     # one snapshot for the three reads; in WAL no write waits
            readings = db.execute(
                "SELECT provider, account, meter, at, used, plan FROM meter_readings "
                "WHERE source = 'probe' AND typeof(used) IN ('integer', 'real') AND used >= 0 "
                "AND used <= 100 AND typeof(at) IN ('integer', 'real') AND at >= ? AND at <= ? "
                "ORDER BY at, rowid", (since, until)).fetchall()
            seats = db.execute("SELECT account, event, model, at, tokens FROM seat_usage "
                               "WHERE at > ? AND at <= ?", (since, until)).fetchall()
            turns = db.execute("SELECT account, turn, model, at, input, cache_write, cache_read, "
                               "output FROM turn_usage WHERE at > ? AND at <= ?",
                               (since, until)).fetchall()
    except (OSError, sqlite3.Error):
        return []
    logins = {}     # {(provider, account): [(at, used, plan)] in order}
    for provider, account, meter, *reading in readings:
        if meters.get((provider, account)) == meter:
            logins.setdefault((provider, account), []).append(reading)
    # (account, harness, model, at, tokens) of each row: a seat's harness its event's text before
    # the first `:`, a turn's its `harness` receipt
    rows = [(account, event.split(":", 1)[0] if isinstance(event, str) else None, model, at,
             tokens) for account, event, model, at, tokens in seats if type(tokens) is int]
    rows += [(account, spend._harness(turn) if isinstance(turn, str) else None, model, at,
              sum(count or 0 for count in counts)) for account, turn, model, at, *counts in turns
             if all(count is None or type(count) is int for count in counts)]
    ran = {}        # {(provider, account): [(at, model, tokens)]}
    for account, harness, model, at, tokens in rows:
        for provider in ours:
            if tokens > 0 and ours[provider](harness):
                ran.setdefault((provider, account), []).append((at, model, tokens))
    found = {}      # {(provider, account, plan, day): ([points], {model: tokens})}
    for login, readings in logins.items():
        kept = sorted(ran.get(login, []), key=lambda row: row[0])
        times = [at for at, *_ in kept]
        for (began, low, plan), (at, used, then) in zip(readings, readings[1:]):
            step = kept[bisect_right(times, began):bisect_right(times, at)]
            if (not isinstance(plan, str) or plan != then or used < low
                    or any(not isinstance(model, str) for _, model, _ in step)):
                continue
            points, tokens = found.setdefault((*login, plan, int(at // DAY)), ([], {}))
            points.append(used - low)
            for _, model, count in step:
                tokens[model] = tokens.get(model, 0) + count
    return [(provider, plan, math.fsum(points), tokens)
            for (provider, _, plan, _), (points, tokens) in found.items()]
