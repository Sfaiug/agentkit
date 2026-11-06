"""What a login spent at listed prices: each token ak keeps by login, model and type -- a seat's
in `seat_usage` (seat_tokens.py), a worker turn's in `turn_usage` (history.py) -- priced at its
model's listed price for its type.

Raw token sums count a cache read like fresh input, though a model lists it at a fraction of
that price.  Priced per type, a login's spend foretold its subscription's next meter readings
within 2-8%, where raw sums were 23% to 75% off (the owner's back-test, 6 Nov 2026).
"""

import contextlib
import functools
from pathlib import Path
import sqlite3

from . import boards, catalog, config, history, matrix

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
        if prices(model) is None or None in counts:
            unpriced += tokens or 0
            continue
        found = True
        dollars += sum(count * price for count, price in zip(counts, prices(model))) / 1e6
        priced += tokens or 0
    if not found:
        return None
    return dollars + (unpriced * dollars / priced if priced else 0.0)


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
