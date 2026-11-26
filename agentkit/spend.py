"""What a login spent at listed prices: each token ak keeps by login, model and type -- a seat's
in `seat_usage` (seat_tokens.py), a worker turn's in `turn_usage` (history.py) -- priced at its
model's listed price for its type.

Raw token sums count a cache read like fresh input, though a model lists it at a fraction of
that price.  Priced per type, a login's spend foretold its subscription's next meter readings
within 2-8%, where raw sums were 23% to 75% off (the owner's back-test, 6 Nov 2026): `weeks`
fits each plan's points of a week a listed dollar takes from every login's readings on it, and
`roles` prices each role of a task in those points.
"""

import contextlib
import fractions
import functools
import json
import math
from pathlib import Path
import sqlite3
import sys
import time

from . import boards, catalog, config, history, matrix

# a reading is of the week of the one before it, by `resets_at`, at most this many seconds later
DRIFT = 600
# a week read from fewer points of its meter names nothing: the meters read whole points and trail
# what bought them, which a few points cannot outweigh.  On 7 Nov 2026 one read from 2 points
# foretold a day's rise eleven times what it was.  More readings only make it matter less.
FEWEST_POINTS = 10
# each count a row keeps, and the column of a release's values listing its price a million tokens
PRICES = {"input": "aa.price1mInputTokens", "cache_write": "aa.cacheWritePrice",
          "cache_read": "aa.cacheHitPrice", "output": "aa.price1mOutputTokens"}


def listed(cfg, provider, account, since, until):
    """The dollars the login `account` of `provider` (None, its usual one) spent between `since`
    and `until` at listed prices; None where none of its rows from then can be priced.

    A row is the login's where its account is and its harness is the provider's (`_ours`).  A
    row it cannot price, its model listing no price, its counts unknown or its cost no float's,
    costs what the login's priced rows cost a token.  A row costs the dollars it kept
    (`history`, `seat_tokens`), whatever the boards list now; one without is priced as it is read.
    """
    return _listed(_ours(cfg, provider), _pricing(), account, since, until)


def _listed(ours, prices, account, since, until):
    """`listed`, its rows `ours` priced at `prices`, so that a week (`weeks`) prices each of its
    stretches from the boards parsed once for it."""
    dollars, priced, unpriced, found = 0.0, 0, 0, False
    for harness, model, tokens, counts, kept in _rows(account or config.DEFAULT_ACCOUNT, since,
                                                      until):
        if not ours(harness):
            continue
        spent = _cost(prices, model, counts, kept)
        if spent is None:
            unpriced += tokens or 0
            continue
        found = True
        dollars += spent
        priced += tokens or 0
    if not found:
        return None
    # the tokens' ratio first: dollars near a float's largest times tokens overflow where the
    # estimate does not
    return dollars + (dollars * (unpriced / priced) if priced else 0.0)


def weeks(cfg, meters, windows):
    """{provider: [{account: (the plan its login is on now (`usage.plan`), what a week of that plan
    holds in listed dollars, and the points and dollars that is read from)}] of each of `windows`,
    (since, until) each} for each login of each provider in `meters`, {provider: {account, None
    for the usual one: the meter `usage.shared_week` names for it}}.

    A plan's points over its dollars are the points of a week a listed dollar takes, summed
    over every login's readings on it between `since` and `until`: those its probes kept, their
    `used` and `resets_at` numbers (a REAL column keeps a text like `nan` as text), a
    model's own cap of that meter's name (`scope`) no reading of it, as a turn's trail them (on
    6 Nov one read 75 eight seconds after a probe read 76), one kept with no plan its login's
    plan now's; logins on plans of one name share that fit, whatever `price` each holds, left
    so by the owner, 21 Nov 2026.  A login's readings of one plan and one week, by DRIFT, are
    cut in time order between any two between which a turn of its provider ran whose tokens ak
    does not know (`_unknown`), as what that turn spent counts nowhere.  Each stretch rose from
    its earliest reading to its highest, as a probe may read lower than one before it; what the
    login spent (`listed`) from the earliest to the first at the highest bought that rise, and
    one whose spend cannot be priced counts for nothing.  A week holds nothing anyone can name
    while its plan's points are under FEWEST_POINTS or its dollars 0.
    """
    from . import usage   # here, not at the top: usage reads this module as it loads
    plans = {(provider, account): usage.plan(provider, account)
             for provider, accounts in meters.items() for account in accounts}
    groups, start, last = {}, {}, {}
    for window, (since, until) in enumerate(windows):
        for provider, account in plans:
            for used, resets_at, at, plan in _select(
                    "SELECT used, resets_at, at, plan FROM meter_readings WHERE provider = ? AND "
                    "account = ? AND meter = ? AND {added[meter_readings.scope]} IS NULL AND "
                    "source = 'probe' AND at >= ? AND at <= ? AND typeof(used) IN ('integer', "
                    "'real') AND typeof(resets_at) IN ('integer', 'real') ORDER BY resets_at",
                    provider, account or config.DEFAULT_ACCOUNT, meters[provider][account],
                    since, until):
                key = window, provider, account, plan or plans[provider, account]
                if key not in last or resets_at - last[key] > DRIFT:
                    start[key] = resets_at
                last[key] = resets_at
                groups.setdefault((*key, start[key]), []).append((at, used))
    # read once, from the earliest window, as a turn that ended before a window's first reading
    # cuts nothing in it, and for every provider, as only which harnesses are its (`_ours`)
    # differs: read for each of `usage.plan_checks`'s fourteen, they took the owner 9.4 s
    unknown = _unknown(min(since for since, _ in windows))
    ours, prices = {provider: _ours(cfg, provider) for provider in meters}, _pricing()
    fits = {}
    for (window, provider, account, plan, _), readings in groups.items():
        spans = [(began, end) for began, end, harness in
                 unknown.get(account or config.DEFAULT_ACCOUNT, []) if ours[provider](harness)]
        for stretch in _stretches(readings, spans):
            began, base = stretch[0]
            top = max(used for _, used in stretch)
            dollars = _listed(ours[provider], prices, account, began,
                              min(at for at, used in stretch if used == top))
            if dollars is not None:
                points, spent = fits.get((window, provider, plan), (0, 0))
                fits[window, provider, plan] = points + top - base, spent + dollars
    # Multiplied by 100 before it is divided, so a spend within two digits of a float's largest
    # fits an infinite week: left so.  A login's week is thousands of dollars, and dividing
    # first made Python and Go differ in sign and rounding (three reviews of run 20261118-0942,
    # 18 Nov 2026): a spend nobody has is not served.
    held = {key: (100 * dollars / points if points >= FEWEST_POINTS and dollars else None,
                  points, dollars)
            for key, (points, dollars) in fits.items()}
    return {provider: [{account: (plan, *held.get((window, provider, plan), (None, 0, 0)))
                        for (of, account), plan in plans.items() if of == provider}
                       for window in range(len(windows))]
            for provider in meters}


def _sum(values):
    """`sum(values)`, falling back to exact Fractions if float addition overflows."""
    if any(isinstance(one, fractions.Fraction) for one in values):
        return sum(fractions.Fraction(one) for one in values)
    total = sum(values)
    return total if math.isfinite(total) else sum(fractions.Fraction(one) for one in values)


def _mean_value(total, runs):
    """`total / runs` as a float when it is normal (or exact zero), else an exact Fraction so
    `matrix._costs` scales subnormal or out-of-range values without losing precision and
    `matrix.dumped` prints them without emitting Infinity."""
    exact = total / runs
    if isinstance(exact, fractions.Fraction):
        out = matrix._to_float(exact)
        return out if out is not None and (exact == 0 or abs(out) >= sys.float_info.min) else exact
    if not math.isfinite(exact) or (total and abs(exact) < sys.float_info.min):
        return fractions.Fraction(total) / runs
    return exact


def roles(cfg):
    """(logins, shares) for `matrix._costs`.  `logins`: {provider: [(price, week)] of each login
    it still lists (`config.lists`) whose week holds some listed dollars, named or usual: what
    it costs a month (`usage.price`) and what its week holds (`usage.plan_weeks`)}, as a login
    removed is signed out, though the usage cache keeps it until it next refreshes and its week
    still prices the runs it did.  `shares`: {model: {effort: {role: (share, runs, listed)}}},
    of each configured model at each effort it did a role at, the means over the `runs` task
    runs that ended where it did of the dollars at listed prices the role's rows took, `listed`,
    and of the points of a week that is, `share`: each row's dollars times 100 over the week of
    its login under the model's provider.  A worker role's rows are its `turn_usage` rows; a
    run's reviewer is at the one effort its reviews name; a run counts for nothing in a worker
    role a counted turn of which kept no row, or rows counting a token none of which names the
    model its entry runs (`model`), a row of which has no listed price or a login of which has no
    week: the run names the role's last model alone, and a turn of another's would be priced as
    its.  A turn naming it beside another's (a subagent's) counts whole, though the role was
    then handed on to that other: left so by the owner, 21 Nov 2026, no run of theirs being
    one.  The orchestrator's rows are every `seat_usage` row naming the model and
    effort, its subagents' and its talk with its owner too, as orchestrating takes them all,
    that counts a token, over the task runs naming them, ended or not, as its seat has written
    and launched one that still runs, that started no earlier than the first, as one before has
    no usage to set against it; none where a row has no listed price or a login no week."""
    from . import staffing, usage   # here, not at the top: usage reads this module as it loads
    held = {name: prov for name, prov in staffing._cached_providers().items()
            if name in cfg["providers"]}
    plans = usage.plan_weeks(cfg, held, time.time())
    weeks = {(provider, account or config.DEFAULT_ACCOUNT): fit[1]
             for provider, logins in plans.items() for account, fit in logins.items()}
    prices = _pricing()
    providers = {name: cfg["models"][name]["provider"] for name in config.offered(cfg)}
    ids = {name: cfg["models"][name].get("model") for name in providers}
    did, kept = {}, {}  # did: (run, role): (model, effort, the turns of it `counted_turns` names)
    # one read, as a run resumed between two would add its new turns' rows to its ended sample
    for (run, executor, effort, reviewer, reviewed, counted, turn, role, account, model,
         listed_usd, *counts) in _select(
            "SELECT run_id, executor, executor_effort, reviewer, (SELECT CASE WHEN "
            "COUNT(DISTINCT effort) = 1 THEN MIN(effort) END FROM reviews WHERE "
            "reviews.run_id = runs.run_id), counted_turns, turn, role, account, model, "
            f"{{added[turn_usage.listed_usd]}}, {', '.join(PRICES)} FROM runs "
            "LEFT JOIN turn_usage USING (run_id) "
            "WHERE kind = 'task' AND finished_at IS NOT NULL"):
        if turn is not None:
            kept.setdefault((run, role), []).append((turn, account, model, counts, listed_usd))
        who = {"executor": (executor, effort), "reviewer": (reviewer, reviewed)}
        for name in json.loads(counted or "[]"):
            mine = "reviewer" if Path(name).name.startswith("reviewer") else "executor"
            did.setdefault((run, mine), (*who[mine], set()))[2].add(name)

    def spent(name, rows):
        """[points, dollars] `rows`, (account, model, counts, listed_usd) each, took on model
        `name`'s provider; None where one has no listed price or its login no week."""
        each = []
        for account, model, counts, listed_usd in rows:
            dollars = _cost(prices, model, counts, listed_usd)
            week = weeks.get((providers[name], account))
            if dollars is None or week is None or week <= 0 or not math.isfinite(dollars):
                return None
            if math.isinf(week):
                points = 0.0
            else:
                points = 100 * dollars / week
                if not math.isfinite(points) or (dollars and abs(points) < sys.float_info.min):
                    points = (fractions.Fraction(100) * fractions.Fraction(dollars)
                              / fractions.Fraction(week))
            each.append((points, dollars))
        return [_sum(one) for one in zip(*each)] if each else None
    samples = {}
    for (run, role), (name, effort, turns) in did.items():
        rows = kept.get((run, role), [])
        # the models each turn's rows counting a token name, as a harness files a message it
        # made up itself with none: one naming the entry's beside others' (a subagent's) is its
        ran = {}
        for turn, _, model, counts, _ in rows:
            if any((count or 0) > 0 for count in counts):
                ran.setdefault(turn, set()).add(model)
        if (name in providers and effort is not None and not turns - {turn for turn, *_ in rows}
                and all(ids[name] in ran[turn] for turn in turns & ran.keys())
                and (one := spent(name, [row[1:] for row in rows]))):
            samples.setdefault((name, effort, role), []).append(one)
    # (model, effort, role): ([points, dollars] summed over its runs, how many)
    totals = {key: ([_sum(one) for one in zip(*runs)], len(runs)) for key, runs in samples.items()}
    seats = {}      # (model, effort, the runs counted): its seats' rows
    # The runs counted in the read of the rows, as one launched between two reads would be set
    # against usage read before it, and in SQL: a seat keeps a row of each message it takes.
    # Only its rows counting a token, in all or of a type: a harness files a message it made up
    # itself with none, under a model no board lists, and that row would leave the measure out.
    for name, effort, runs, account, model, listed_usd, *counts in _select(
            f"WITH used AS (SELECT * FROM seat_usage WHERE tokens > 0 OR "
            f"{' > 0 OR '.join(PRICES)} > 0), "
            "firsts AS (SELECT orchestrator, effort, MIN(at) AS first FROM used "
            "GROUP BY 1, 2), launched AS (SELECT firsts.orchestrator, firsts.effort, COUNT(*) "
            "AS runs FROM firsts JOIN runs ON runs.orchestrator = firsts.orchestrator AND "
            "orchestrator_effort = firsts.effort AND started_at >= first WHERE kind = 'task' "
            "GROUP BY 1, 2) SELECT orchestrator, effort, runs, account, "
            f"model, {{added[seat_usage.listed_usd]}}, {', '.join(PRICES)} FROM used "
            "JOIN launched USING (orchestrator, effort)"):
        seats.setdefault((name, effort, runs), []).append((account, model, counts, listed_usd))
    for (name, effort, runs), rows in seats.items():
        if name in providers and (one := spent(name, rows)):
            totals[name, effort, "orchestrator"] = one, runs
    found = {}
    for (name, effort, role), ((points, listed), runs) in totals.items():
        found.setdefault(name, {}).setdefault(effort, {})[role] = (
            _mean_value(points, runs), runs, _mean_value(listed, runs))
    return {provider: [(usage.price(cfg, provider, account), fit[1])
                       for account, fit in logins.items()
                       if fit[1] and config.lists(cfg, provider, account)]
            for provider, logins in plans.items()}, found


def _rows(account, since, until):
    """(harness, model, tokens, counts by `PRICES`, dollars kept) of the login's rows between
    `since` and `until`: a seat row at its `at`, a turn row the share of its span, from its
    `began` to its `at`, that falls between them, one with no `began` at its `at`.  A seat row's
    harness is its event's text before the first `:`, a turn row's the one its turn's `harness`
    receipt names, None once that is gone; a seat row's tokens are its own, a turn row's its
    counts summed; a row's dollars are those it kept, if any, a turn row's that share of them."""
    columns = ", ".join(PRICES)
    for event, model, tokens, kept, *counts in _select(
            f"SELECT event, model, tokens, {{added[seat_usage.listed_usd]}}, {columns} "
            "FROM seat_usage "
            "WHERE account = ? AND at >= ? AND at <= ?", account, since, until):
        yield event.split(":", 1)[0], model, tokens, counts, kept
    for turn, model, began, at, kept, *counts in _select(
            "SELECT turn, model, COALESCE(began, at), at, {added[turn_usage.listed_usd]}, "
            f"{columns} FROM turn_usage "
            "WHERE account = ? AND at >= ? AND COALESCE(began, at) <= ?", account, since, until):
        share = (min(at, until) - max(began, since)) / (at - began) if at > began else 1
        if not share:   # it only touches the time at an end: none of it was spent then
            continue
        counts =[None if count is None else count * share for count in counts]
        yield (_harness(turn), model, sum(count or 0 for count in counts), counts,
               None if kept is None else kept * share)


@functools.cache
def _harness(turn):
    """The `harness` receipt of a turn that kept a `turn_usage` row, read once in a process: a row
    is written once its turn has ended, and the receipt changes no more after that.  Read for
    each of its rows in each provider's pricing, they took the owner 5.9 s of an `ak usage`."""
    return _receipt(turn, "harness")


def _unknown(since):
    """{login: [(began, end, harness)], in order of `began`} of each worker turn whose tokens ak
    does not know: one that kept no `turn_usage` row, either one `counted_turns` names or one of
    a run that has not ended.  A run that ended before `since` ran none since.  A turn is its
    `account` receipt's login, the usual one where it names none, and ran from its `harness`
    receipt to its last event (`history._turn_usage`).

    Only these turns' directories are read: listing every run's took the owner 12.7 s cold."""
    counted, kept, running = {}, set(), set()   # counted: {turn: when its run ended, or None}
    for run, ended, turns, turn in _select(
            "SELECT run_id, finished_at, counted_turns, turn FROM runs "
            "LEFT JOIN turn_usage USING (run_id) WHERE finished_at IS NULL OR finished_at >= ?",
            since):
        counted.update(dict.fromkeys(json.loads(turns or "[]"), ended))
        kept.add(turn)
        if ended is None:
            running.add(run)
    counted.update(dict.fromkeys((str(receipt.parent.resolve()) for run in running
                                  for receipt in (config.RUNS / run).glob("round-*/*/harness"))))
    spans = {}
    for turn in counted.keys() - kept:
        ended = counted[turn]
        began, end, harness, login = _turn(turn) if ended is None else _ended(turn, ended)
        if began is not None:
            spans.setdefault(login, []).append((began, end, harness))
    return {login: sorted(turns, key=lambda turn: turn[0]) for login, turns in spans.items()}


def _turn(turn):
    """(began, end, harness, login) of the turn in directory `turn`, as `_unknown` reads them;
    `began` None once its `harness` receipt is gone."""
    began = history._moment(Path(turn) / "harness")
    return (began, history._moment(Path(turn) / "events.jsonl") or began,
            _receipt(turn, "harness"), _receipt(turn, "account") or config.DEFAULT_ACCOUNT)


@functools.cache
def _ended(turn, ended):
    """`_turn` of a turn of a run that ended at `ended`, read once in a process, as it changes
    no more and `ak usage` prices the plans' weeks, then the windows it checks.  A resume
    reopens its run's last round, so a run that ends again is read anew."""
    return _turn(turn)


def _stretches(readings, spans):
    """`readings`, (at, used) each, in time order, cut between any two a span (began, end) of
    `spans`, in order of `began`, overlaps the time between: cut in one pass over both, as
    testing each reading against every span took the owner 3.6 s of an `ak usage`."""
    stretch, reach, n = [], float("-inf"), 0    # reach: the latest end of a span begun before
    for at, used in sorted(readings):
        while n < len(spans) and spans[n][0] < at:
            reach = max(reach, spans[n][1])
            n += 1
        if stretch and reach > stretch[-1][0]:
            yield stretch
            stretch = []
        stretch.append((at, used))
    yield stretch


def _ours(cfg, provider):
    """Whether a harness runs models of `provider` alone (`config.harness_providers`), so that
    what ran on it is the provider's."""
    return functools.cache(lambda harness: config.harness_providers(cfg, harness) == [provider])


def _receipt(turn, name):
    """A turn directory's receipt `name` as `worker` wrote it, None once it is gone."""
    try:
        return (Path(turn) / name).read_text().strip()
    except OSError:
        return None


# The columns a migration added that a query here reads as `{added[<table>.<column>]}`.
ADDED = ("seat_usage.listed_usd", "turn_usage.listed_usd", "meter_readings.scope")


def _select(query, *args):
    """What `query` finds in history.db; nothing where it cannot answer, as before a table is.
    Its `{added[<table>.<column>]}` of a column ADDED names is that column, or NULL in a
    history.db no write has added it to yet, as a read connection adds no column.  Looked for in
    the query's own read: a write adding it and a row between a look and the query left that
    row's column unread."""
    try:
        with contextlib.closing(history._connect(readonly=True)) as db:
            db.execute("BEGIN")     # one snapshot for the look and the query; in WAL no write waits
            added = {name: name.split(".")[1] if db.execute(
                         "SELECT 1 FROM pragma_table_info(?) WHERE name = ?",
                         name.split(".")).fetchone() else "NULL"
                     for name in ADDED}
            return db.execute(query.format(added=added), args).fetchall()
    except (OSError, sqlite3.Error):
        return []


def _cost(prices, model, counts, kept):
    """A row's dollars: those it kept, else its `counts` at its `model`'s `prices` now."""
    return _dollars(prices(model), counts) if kept is None else kept


def _dollars(prices, counts):
    """What a row's `counts` by `PRICES` cost at `prices`, a million tokens of each; None where
    either is unknown or the cost is no float's, as a board listing an infinite price, one near
    a float's largest or an integer past it: summed, it would leave every cost it joins infinite
    or NaN, or raise."""
    if prices is None or None in counts:
        return None
    # Multiplied before it is scaled, so a product past a float's largest prices nothing though
    # scaled first it would: left so.  No board lists a price within hundreds of digits of
    # that, and pricing it exactly made Python and Go differ on stored integers (three reviews
    # of run 20261118-0942, 18 Nov 2026): an input nobody has is refused, not served.
    try:
        dollars = sum(count * price for count, price in zip(counts, prices)) / 1e6
    except OverflowError:   # json reads an integer whole, and one past a float's largest
        return None
    return dollars if math.isfinite(dollars) else None


def _pricing():
    """`_prices` of each model, each found once, from the boards as they are when the first is
    priced: each pricing asks for its own, as the menu runs for days and a fetch may change them."""
    index = functools.cache(lambda: matrix._release_index(catalog.current(boards.cached())))
    return functools.cache(lambda model: _prices(index(), model))


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
