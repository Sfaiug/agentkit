"""What a login spent at listed prices: each token ak keeps by login, model and type -- a seat's
in `seat_usage` (seat_tokens.py), a worker turn's in `turn_usage` (history.py) -- priced at its
model's listed price for its type.

Raw token sums count a cache read like fresh input, though a model lists it at a fraction of
that price.  Priced per type, a login's spend foretold its subscription's next meter readings
within 2-8%, where raw sums were 23% to 75% off (the owner's back-test, 6 Nov 2026): `weeks`
fits each plan's points of a week a listed dollar takes from every login's readings on it, and
`roles` prices each run's worker roles in those points.
"""

import contextlib
import functools
import json
from pathlib import Path
import sqlite3
import time

from . import boards, catalog, config, history, matrix

# a reading is of the week of the one before it, by `resets_at`, at most this many seconds later
DRIFT = 600
# each count a row keeps, and the column of a release's values listing its price a million tokens
PRICES = {"input": "aa.price1mInputTokens", "cache_write": "aa.cacheWritePrice",
          "cache_read": "aa.cacheHitPrice", "output": "aa.price1mOutputTokens"}


def listed(cfg, provider, account, since, until):
    """The dollars the login `account` of `provider` (None, its usual one) spent between `since`
    and `until` at listed prices; None where none of its rows from then can be priced.

    A row is the login's where its account is and its harness runs models of that provider
    alone (`config.harness_providers`).  A row it cannot price, its model listing no price or
    its counts unknown, costs what the login's priced rows cost a token.
    """
    index = matrix._release_index(catalog.current(boards.cached()))
    ours = functools.cache(lambda harness: config.harness_providers(cfg, harness) == [provider])
    prices = functools.cache(lambda model: _prices(index, model))
    dollars, priced, unpriced, found = 0.0, 0, 0, False
    for harness, model, tokens, counts in _rows(account or config.DEFAULT_ACCOUNT, since, until):
        if not ours(harness):
            continue
        spent = _dollars(prices(model), counts)
        if spent is None:
            unpriced += tokens or 0
            continue
        found = True
        dollars += spent
        priced += tokens or 0
    if not found:
        return None
    return dollars + (unpriced * dollars / priced if priced else 0.0)


def weeks(cfg, provider, meters, since, until):
    """{account: (its plan as state/logins.json names it now, what a week of that plan holds in
    listed dollars, and the points and dollars that is read from)} for each login of `provider`
    in `meters`, {account, None for the usual one: the meter `usage.shared_week` names for it}.

    A plan's points over its dollars are the points of a week a listed dollar takes, summed
    over every login's readings on it between `since` and `until`: those its probes kept, as a
    turn's trail them (on 6 Nov one read 75 eight seconds after a probe read 76), one kept with
    no plan its login's plan now's.  A login's readings of one plan and one week, by DRIFT, rose
    from the earliest to the highest, as a probe may read lower than one before it; what the
    login spent (`listed`) from the earliest to the first at the highest bought that rise, and
    one whose spend cannot be priced counts for nothing.  A week holds nothing anyone can name
    while its plan's points or dollars are 0.
    """
    from . import logins    # here, not at the top: logins names subscriptions through the menu
    plans = {account: logins.whose(provider, account)[1] for account in meters}
    groups, start, last = {}, {}, {}
    for account, meter in meters.items():
        for used, resets_at, at, plan in _select(
                "SELECT used, resets_at, at, plan FROM meter_readings WHERE provider = ? AND "
                "account = ? AND meter = ? AND source = 'probe' AND at >= ? AND at <= ? AND "
                "used IS NOT NULL AND resets_at IS NOT NULL ORDER BY resets_at",
                provider, account or config.DEFAULT_ACCOUNT, meter, since, until):
            key = account, plan or plans[account]
            if key not in last or resets_at - last[key] > DRIFT:
                start[key] = resets_at
            last[key] = resets_at
            groups.setdefault((*key, start[key]), []).append((at, used))
    fits = {}
    for (account, plan, _), readings in groups.items():
        began, base = min(readings)
        top = max(used for _, used in readings)
        dollars = listed(cfg, provider, account, began,
                         min(at for at, used in readings if used == top))
        if dollars is not None:
            points, spent = fits.get(plan, (0, 0))
            fits[plan] = points + top - base, spent + dollars
    held = {plan: (100 * dollars / points if points and dollars else None, points, dollars)
            for plan, (points, dollars) in fits.items()}
    return {account: (plan, *held.get(plan, (None, 0, 0))) for account, plan in plans.items()}


def roles(cfg):
    """{model: {effort: {role: share}}} for `matrix._costs`: of each configured model at each
    effort it did a worker role at, the mean over the task runs that ended where it did of the
    points of a week the role's `turn_usage` rows took, at listed prices times 100 over the week
    of each row's login under the model's provider (`usage.plan_weeks`).  A run's reviewer is at
    the one effort its reviews name; a run counts for nothing in a role a counted turn of which
    kept no row, a row of which has no listed price or a login of which has no week."""
    from . import staffing, usage   # here, not at the top: usage reads this module as it loads
    held = {name: prov for name, prov in staffing._cached_providers().items()
            if name in cfg["providers"]}
    weeks = {(provider, account or config.DEFAULT_ACCOUNT): fit[1]
             for provider, logins in usage.plan_weeks(cfg, held, time.time()).items()
             for account, fit in logins.items()}
    index = matrix._release_index(catalog.current(boards.cached()))
    prices = functools.cache(lambda model: _prices(index, model))
    providers = {name: cfg["models"][name]["provider"] for name in config.offered(cfg)}
    did = {}    # (run, role): (model, effort, the turns of it `counted_turns` names)
    for run, executor, effort, reviewer, reviewed, counted in _select(
            "SELECT run_id, executor, executor_effort, reviewer, (SELECT CASE WHEN "
            "COUNT(DISTINCT effort) = 1 THEN MIN(effort) END FROM reviews WHERE "
            "reviews.run_id = runs.run_id), counted_turns FROM runs "
            "WHERE kind = 'task' AND finished_at IS NOT NULL"):
        who = {"executor": (executor, effort), "reviewer": (reviewer, reviewed)}
        for turn in json.loads(counted or "[]"):
            role = "reviewer" if Path(turn).name.startswith("reviewer") else "executor"
            did.setdefault((run, role), (*who[role], set()))[2].add(turn)
    kept = {}
    for run, turn, role, account, model, *counts in _select(
            f"SELECT run_id, turn, role, account, model, {', '.join(PRICES)} FROM turn_usage"):
        kept.setdefault((run, role), []).append((turn, account, model, counts))
    samples = {}
    for (run, role), (name, effort, turns) in did.items():
        rows = kept.get((run, role), [])
        if name not in providers or effort is None or turns - {turn for turn, *_ in rows}:
            continue
        points = [100 * spent / week for _, account, model, counts in rows
                  if (spent := _dollars(prices(model), counts)) is not None
                  and (week := weeks.get((providers[name], account))) is not None]
        if len(points) == len(rows):
            samples.setdefault((name, effort, role), []).append(sum(points))
    found = {}
    for (name, effort, role), points in samples.items():
        found.setdefault(name, {}).setdefault(effort, {})[role] = sum(points) / len(points)
    return found


def _rows(account, since, until):
    """(harness, model, tokens, counts by `PRICES`) of each of the login's rows that ended between
    `since` and `until`: a seat row's harness is its event's text before the first `:`, a turn
    row's the one its turn's `harness` receipt names, None once that is gone; a seat row's
    tokens are its own, a turn row's its counts summed."""
    columns = ", ".join(PRICES)
    for event, model, tokens, *counts in _select(
            f"SELECT event, model, tokens, {columns} FROM seat_usage "
            "WHERE account = ? AND at >= ? AND at <= ?", account, since, until):
        yield event.split(":", 1)[0], model, tokens, counts
    for turn, model, *counts in _select(
            f"SELECT turn, model, {columns} FROM turn_usage "
            "WHERE account = ? AND at >= ? AND at <= ?", account, since, until):
        try:
            harness = (Path(turn) / "harness").read_text().strip()
        except OSError:
            harness = None
        yield harness, model, sum(count or 0 for count in counts), counts


def _select(query, *args):
    """What `query` finds in history.db; nothing where it cannot answer, as before a table is."""
    try:
        with contextlib.closing(history._connect(readonly=True)) as db:
            return db.execute(query, args).fetchall()
    except (OSError, sqlite3.Error):
        return []


def _dollars(prices, counts):
    """What a row's `counts` by `PRICES` cost at `prices`, a million tokens of each; None where
    either is unknown."""
    if prices is None or None in counts:
        return None
    return sum(count * price for count, price in zip(counts, prices)) / 1e6


def _prices(index, model):
    """A model's listed price a million tokens of each of `PRICES`, None where it has none.

    They are its release's among `catalog.current`'s, the one `matrix.found` finds alone, at the
    release's default effort, else its first; a cache price it lists none of is its input
    price, and one listing no input or output price has none."""
    releases = {hit["release"]["slug"]: hit["release"]
                for hit in (matrix.found(index, model) if model else [])}
    if len(releases) != 1:
        return None
    [release] = releases.values()
    efforts = release["efforts"]
    values = next((effort for effort in efforts if effort["default"]), efforts[0])["values"]
    fresh = values.get(PRICES["input"])
    if fresh is None or PRICES["output"] not in values:
        return None
    return [values.get(column, fresh) for column in PRICES.values()]
